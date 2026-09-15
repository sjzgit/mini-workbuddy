"""OpenAI Chat Completions 兼容调用（002 测试连接 + 008 聊天流式）。

地址规范化规则（002 research R3）：
  normalize(base) = 去末尾斜杠；末段不是 v1 时补 /v1
  请求地址 = normalize(base) + /chat/completions

错误分类（research R4）由 model_service / chat_service 完成，
本模块只暴露原始异常/状态与流式增量。
"""

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal

import httpx

from app.core.config import settings
from app.schemas.model import (
    TEST_CONNECTION_MAX_TOKENS,
    TEST_CONNECTION_PROMPT,
    TEST_CONNECTION_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


@dataclass
class ChatReply:
    """一次对话补全的结果。"""

    content: str  # 首个 choice 的文本


def normalize_base_url(base_url: str) -> str:
    """规范化服务地址：去末尾斜杠；末段非 v1 时补 /v1。"""
    normalized = base_url.rstrip("/")
    if normalized.split("/")[-1].lower() != "v1":
        normalized += "/v1"
    return normalized


def chat_completions_url(base_url: str) -> str:
    """拼装 Chat Completions 请求地址。"""
    return f"{normalize_base_url(base_url)}/chat/completions"


def send_test_message(base_url: str, model_identifier: str, api_key: str | None) -> ChatReply:
    """发送测试连接用短消息（30s 超时；异常原样上抛给分类层）。

    httpx 异常与 HTTP 状态由调用方映射为 TestErrorCategory。
    """
    payload = {
        "model": model_identifier,
        "messages": [{"role": "user", "content": TEST_CONNECTION_PROMPT}],
        "max_tokens": TEST_CONNECTION_MAX_TOKENS,
        "temperature": 0.7,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    with httpx.Client(timeout=TEST_CONNECTION_TIMEOUT_SECONDS) as client:
        response = client.post(chat_completions_url(base_url), json=payload, headers=headers)

    if response.status_code != 200:
        # 附带响应体供分类层判断 model_not_found 等（不含请求头/密钥）
        raise ChatHttpError(response.status_code, response.text[:500])

    try:
        body = response.json()
        content = str(body["choices"][0]["message"]["content"])
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise BadResponseFormatError from exc
    return ChatReply(content=content)


class ChatHttpError(Exception):
    """非 200 响应：携带状态码与响应体片段（分类依据）。"""

    def __init__(self, status_code: int, body_snippet: str) -> None:
        super().__init__(f"chat completions http {status_code}")
        self.status_code = status_code
        self.body_snippet = body_snippet


class BadResponseFormatError(Exception):
    """200 但响应无法解析为 Chat Completions 结构。"""


# ---- 008 聊天：异步流式调用（specs/008-chat-conversations/research.md R2/R10）----


@dataclass
class ContentDelta:
    """回答正文增量。"""

    text: str


@dataclass
class ReasoningDelta:
    """思考过程增量。"""

    text: str


def _stream_headers(api_key: str | None) -> dict[str, str]:
    """流式请求头（Authorization 仅存于本函数局部，不进日志）。"""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


async def stream_chat_completion(
    base_url: str,
    model_identifier: str,
    api_key: str | None,
    messages: list[dict[str, str]],
    *,
    temperature: Decimal,
    max_tokens: int,
    enable_thinking: bool,
) -> AsyncIterator[ContentDelta | ReasoningDelta]:
    """流式对话补全：逐增量产出 ContentDelta / ReasoningDelta（research R2）。

    非 200 抛 ChatHttpError（携带响应体片段供分类）；超时/连接异常
    （httpx.TimeoutException / httpx.HTTPError）原样上抛给编排层分类。
    thinking 参数映射：enable_thinking=True → {"type": "enabled"}（GLM 系）。
    """
    payload = {
        "model": model_identifier,
        "messages": messages,
        "stream": True,
        "temperature": float(temperature),
        "max_tokens": max_tokens,
        "thinking": {"type": "enabled" if enable_thinking else "disabled"},
    }
    # FR-011：实时打印请求摘要（不含 Authorization 与密钥）
    logger.info(
        "[chat] 请求第三方模型 API：model=%s messages=%d thinking=%s",
        model_identifier, len(messages), enable_thinking,
    )
    timeout = httpx.Timeout(
        connect=settings.chat_stream_connect_timeout_seconds,
        read=settings.chat_stream_read_timeout_seconds,
        write=30.0,
        pool=30.0,
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST", chat_completions_url(base_url), json=payload,
            headers=_stream_headers(api_key),
        ) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise ChatHttpError(response.status_code, body[:500])
            async for line in response.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue  # 忽略无法解析的心跳/杂项行
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                finish = choices[0].get("finish_reason")
                reasoning = delta.get("reasoning_content")
                content = delta.get("content")
                if reasoning:
                    logger.info("[chat] reasoning 增量 %d 字符", len(str(reasoning)))
                    yield ReasoningDelta(text=str(reasoning))
                if content:
                    logger.info("[chat] content 增量 %d 字符", len(str(content)))
                    yield ContentDelta(text=str(content))
                if finish:
                    logger.info("[chat] finish_reason=%s", finish)

"""OpenAI Chat Completions 兼容调用（本阶段唯一调用逻辑）。

地址规范化规则（research R3）：
  normalize(base) = 去末尾斜杠；末段不是 v1 时补 /v1
  请求地址 = normalize(base) + /chat/completions

错误分类（research R4）由 model_service 完成，本模块只暴露原始异常/状态。
"""

import json
from dataclasses import dataclass

import httpx

from app.schemas.model import (
    TEST_CONNECTION_MAX_TOKENS,
    TEST_CONNECTION_PROMPT,
    TEST_CONNECTION_TIMEOUT_SECONDS,
)


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

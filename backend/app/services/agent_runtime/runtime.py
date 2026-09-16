"""Runtime 主循环（specs/009-agent-runtime 契约 §6；研究 R7/R8）。

execute_run 的循环体：加载配置 → 组装上下文 → 逐轮模型请求 → 工具循环 →
轮数收尾 → 取消与清理。事件产出与资源清理覆盖所有退出路径（FR-029/035）。
"""

import asyncio
import logging
import httpx
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.agent_runtime import RunRequest
    from app.services.agent_runtime.events import RunEventEmitter, RunEvent
    from app.schemas.agent_runtime import UsageInfo as UsageInfoModel

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import secret_vault
from app.core.db import SessionLocal
from app.models import AgentEntry, ModelEntry
from app.schemas.agent_runtime import (
    DeltaData,
    ErrorEventData,
    ModelRequestCompletedData,
    ModelRequestStartedData,
    RunCompletedData,
    RunStartedData,
    ToolCallCompletedData,
    ToolCallStartedData,
    UsageInfo as UsageInfoModel,
)
from app.services import skill_files
from app.services.agent_runtime import events as rt_events
from app.services.agent_runtime.context_builder import ContextBuilder
from app.services.agent_runtime.compression import (
    SUMMARY_ROLE,
    _maybe_compact,
    available_input_tokens,
    estimate_messages_tokens,
    load_compaction,
)
from app.services.agent_runtime.skills import build_skill_catalog_section
from app.services.agent_runtime.tools import (
    ToolCatalogEntry,
    ToolContext,
    build_tool_catalog,
    connect_mcp_servers,
    run_tool,
)
import app.services.openai_client as openai
from app.services.openai_client import (
    ChatHttpError,
    ContentDelta,
    ReasoningDelta,
    ToolCallDelta,
    stream_chat_completion,
)

# 008 既有口径复用（模型请求超时沿用聊天配置）
from app.core.config import settings

logger = logging.getLogger(__name__)

NL2 = chr(10) * 2

# 结束原因文案（FR-035；run_completed.reason）
REASON_COMPLETED = "模型直接给出回答，运行正常结束"
REASON_MAX_ROUNDS = "已达到最大执行轮数限制，已基于已有信息完成收尾回答"
REASON_ERROR = "运行过程中发生错误"
REASON_CANCELLED = "运行被用户取消"

_STREAM_ERROR_MESSAGES = {
    "unreachable": "服务地址不可访问。请检查模型配置中的服务地址是否可达。",
    "timeout": "模型请求超时。请检查网络状况或稍后再试。",
    "auth_error": "认证失败：API Key 无效或无权限。请检查模型配置中的密钥。",
    "model_not_found": "模型标识不存在：服务端不认识该 model 名称。请核对模型配置。",
    "bad_response": "服务返回了无法识别的内容。该地址可能不是 OpenAI Chat Completions 兼容接口。",
    "empty_response": "模型返回了空内容。请重试或更换模型。",
    "stream_interrupted": "流式输出中断，内容不完整。已保留已生成的部分。",
    "context_overflow": "会话历史过长，已超出该模型可用的上下文容量。请缩短输入或新建会话。",
    "unknown": "生成失败，暂时无法确定原因。请稍后重试。",
}


def _truncate_for_display(text: str, max_chars: int) -> str:
    """010 契约 §1：超限截断并追加标记（N 为截断前总字符数）。"""
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n…[已截断，完整内容共 {len(text)} 字符]"


class AgentUnavailableError(ValueError):
    """Agent/模型不可用（桥接层转 400 语义；Runtime 内直接 error 终态）。"""


@dataclass
class RunContext:
    """一次运行的完整上下文（data-model.md §1.1~1.7）。"""

    request: "RunRequest"
    emitter: "RunEventEmitter"
    # 模型与配置（加载后填充）
    agent_name: str = ""
    model_name: str = ""  # 011：模型 display_name 快照（runs 表快照来源）
    base_url: str = ""
    model_identifier: str = ""
    api_key: str | None = None
    temperature: "Any" = None
    max_tokens: int = 0
    enable_thinking: bool = False
    max_rounds: int = 1
    # 运行期状态
    round_no: int = 0
    builder: "ContextBuilder | None" = None
    messages: list[dict[str, Any]] = field(default_factory=list)  # 与 builder.messages 同一对象
    reasoning_parts: list[str] = field(default_factory=list)
    content_parts: list[str] = field(default_factory=list)
    usage_total: "UsageInfoModel | None" = None
    completed_data: "RunCompletedData | None" = None
    # 单次模型请求结果（_stream_model_request 写入）
    last_request_usage: Any = None
    cancel: Any = None
    skill_catalog_ids: frozenset = frozenset()
    pending_tool_calls: list[dict[str, str]] = field(default_factory=list)
    stream_cancelled: bool = False
    stream_error_category: str | None = None
    stream_error_text: str | None = None
    # 工具链
    tool_ctx: "ToolContext | None" = None
    tool_payloads: list[dict[str, Any]] = field(default_factory=list)
    mcp_stacks: dict = field(default_factory=dict)
    # 资源清理注册
    _closed: bool = False
    # ---- 011：上下文压缩状态 ----
    available_input: int = 0
    compact_enabled: bool = False
    compact_trigger_ratio: float = 0.8
    compact_keep_recent_rounds: int = 5
    compact_summary_target_tokens: int = 1000
    compact_summary: str = ""
    compact_prefix_len: int = 0
    compact_attempts: int = 0
    compaction_ok: bool = False
    compact_done_round: int = -1  # 本轮已完成压缩（防同轮重复触发）
    capacity_error: str | None = None
    compact_boundary_seq: int = 0
    effective_history: list | None = None

    async def aclose(self) -> None:
        """资源清理（所有退出路径，FR-029）：关闭 MCP 栈。"""
        if self._closed:
            return
        self._closed = True
        for stack in self.mcp_stacks.values():
            try:
                await stack.aclose()
            except Exception:  # noqa: BLE001 — 清理失败不影响终态
                logger.warning("[runtime] MCP 栈关闭失败", exc_info=True)
        self.mcp_stacks.clear()

    def build_completed_event(self) -> rt_events.RunEvent:
        """终态事件（execute_run 最后 yield；恰一次，FR-035）。"""
        data = self.completed_data or RunCompletedData(
            status="error", reason=REASON_ERROR,
        )
        return self.emitter.emit(
            rt_events.EVENT_RUN_COMPLETED, data, round=0, call_id=None,
        )


# ---- 主循环 ----


def _classify_http_error(exc: ChatHttpError) -> tuple[str, str]:
    """ChatHttpError → (类别, 人话文案)（沿用 008 分类口径）。"""
    body = exc.body_snippet.lower()
    if exc.status_code in (401, 403):
        return "auth_error", _STREAM_ERROR_MESSAGES["auth_error"]
    if exc.status_code == 404 and ("model" in body or "not found" in body):
        return "model_not_found", _STREAM_ERROR_MESSAGES["model_not_found"]
    if exc.status_code == 404:
        return "unreachable", _STREAM_ERROR_MESSAGES["unreachable"]
    fallback = "unreachable" if 400 <= exc.status_code < 600 else "unknown"
    return fallback, _STREAM_ERROR_MESSAGES[fallback]


# ---- 模型请求与流消费 ----


async def _stream_model_request(
    ctx: "RunContext",
    tools: list[dict[str, Any]] | None,
    *,
    purpose: str = "chat",
):
    """一次模型请求的流消费（async generator，契约 §2 事件产出）。

    产出 model_request_started / reasoning_delta / content_delta /
    model_request_completed；结果状态写入 ctx（stream_error_category /
    stream_error_text / last_request_usage / pending_tool_calls / cancelled）。
    正文与思考增量即时进入 ctx 累积（跨轮保留，FR-013）。
    011：completed 事件附带 Recorder 透传字段（request_messages / output_full，
    SSE 前剥离后落 run_payloads）；purpose 标记请求用途（FR-045）。
    """
    round_no = ctx.round_no
    call_id = ctx.emitter.next_call_id("m")
    ctx.pending_tool_calls = []
    ctx.last_request_usage = None
    ctx.stream_cancelled = False
    messages_snapshot = list(ctx.messages)  # 本次请求实际发送的完整输入
    round_reasoning: list[str] = []
    round_content: list[str] = []
    yield ctx.emitter.emit(
        rt_events.EVENT_MODEL_REQUEST_STARTED,
        ModelRequestStartedData(round=round_no, call_id=call_id, purpose=purpose),
        round=round_no, call_id=call_id,
    )
    started = time.monotonic()
    error_category: str | None = None
    error_text: str | None = None
    try:
        async for delta in stream_chat_completion(
            ctx.base_url, ctx.model_identifier, ctx.api_key,
            ctx.messages,
            temperature=ctx.temperature, max_tokens=ctx.max_tokens,
            enable_thinking=ctx.enable_thinking,
            tools=tools,
            include_usage=True,
        ):
            if ctx.request.cancel.is_set():
                ctx.stream_cancelled = True
                break
            if isinstance(delta, openai.UsageInfo):
                ctx.last_request_usage = UsageInfoModel(
                    prompt_tokens=delta.prompt_tokens,
                    completion_tokens=delta.completion_tokens,
                    total_tokens=delta.total_tokens,
                )
            elif isinstance(delta, ReasoningDelta):
                ctx.reasoning_parts.append(delta.text)
                round_reasoning.append(delta.text)
                yield ctx.emitter.emit(
                    rt_events.EVENT_REASONING_DELTA,
                    DeltaData(round=round_no, call_id=call_id, text=delta.text),
                    round=round_no, call_id=call_id,
                )
            elif isinstance(delta, ContentDelta):
                ctx.content_parts.append(delta.text)
                round_content.append(delta.text)
                yield ctx.emitter.emit(
                    rt_events.EVENT_CONTENT_DELTA,
                    DeltaData(round=round_no, call_id=call_id, text=delta.text),
                    round=round_no, call_id=call_id,
                )
            elif isinstance(delta, ToolCallDelta):
                acc = ctx.pending_tool_calls
                while len(acc) <= delta.index:
                    acc.append({"id": "", "name": "", "arguments": ""})
                slot = acc[delta.index]
                if delta.id:
                    slot["id"] = delta.id
                if delta.name:
                    slot["name"] = delta.name
                slot["arguments"] += delta.arguments_fragment
    except asyncio.CancelledError:
        raise
    except ChatHttpError as exc:
        error_category, error_text = _classify_http_error(exc)
    except httpx.TimeoutException:
        error_category = "timeout"
        error_text = _STREAM_ERROR_MESSAGES["timeout"]
    except httpx.HTTPError:
        error_category = "unreachable"
        error_text = _STREAM_ERROR_MESSAGES["unreachable"]
    except Exception:  # noqa: BLE001 — 未知错误也给终态（FR-035）
        logger.exception("[runtime] model request error round=%s", round_no)
        error_category = "unknown"
        error_text = _STREAM_ERROR_MESSAGES["unknown"]
    duration_ms = int((time.monotonic() - started) * 1000)
    if ctx.stream_cancelled:
        status = "cancelled"
    elif error_category is not None:
        status = "error"
    else:
        status = "ok"
    output_tool_calls = [
        {"name": c.get("name", ""), "arguments": c.get("arguments") or "{}"}
        for c in ctx.pending_tool_calls
    ] or None
    yield ctx.emitter.emit(
        rt_events.EVENT_MODEL_REQUEST_COMPLETED,
        ModelRequestCompletedData(
            round=round_no, call_id=call_id, status=status,
            duration_ms=duration_ms, usage=ctx.last_request_usage,
            purpose=purpose,
            request_messages=messages_snapshot,
            output_content="".join(round_content) or None,
            output_reasoning="".join(round_reasoning) or None,
            output_tool_calls=output_tool_calls,
        ),
        round=round_no, call_id=call_id,
    )
    ctx.stream_error_category = error_category
    ctx.stream_error_text = error_text


# ---- 主循环体 ----


def _completed(
    ctx: "RunContext",
    status: str,
    reason: str,
    *,
    stopped: bool = False,
) -> rt_events.RunEvent:
    """设置终态数据并返回 run_completed 事件（build_completed_event 复用同一数据）。"""
    ctx.completed_data = RunCompletedData(
        status=status, reason=reason,
        usage_total=ctx.usage_total,
        content_text="".join(ctx.content_parts),
        reasoning_text="".join(ctx.reasoning_parts) or None,
        stopped=stopped,
    )
    return ctx.build_completed_event()


def _error_out(ctx, category: str, reason: str) -> list[rt_events.RunEvent]:
    """错误收尾：error 事件 + 终态数据（run_completed 由 execute_run 统一产出）。"""
    ctx.completed_data = RunCompletedData(
        status="error", reason=reason,
        usage_total=ctx.usage_total,
        content_text="".join(ctx.content_parts),
        reasoning_text="".join(ctx.reasoning_parts) or None,
    )
    return [ctx.emitter.emit(
        rt_events.EVENT_ERROR,
        ErrorEventData(category=category, message=reason),
    )]


def _merge_usage(ctx) -> None:
    """把本次请求用量并入累计（未知项保持 None，FR-034）。"""
    usage = ctx.last_request_usage
    if usage is None:
        return
    model_usage = UsageInfoModel(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )
    ctx.usage_total = (
        model_usage if ctx.usage_total is None else ctx.usage_total.merge_add(model_usage)
    )


async def run_agent_loop(ctx: "RunContext"):
    """Agent Loop（契约 §6）：事件流 async generator。

    无工具 → completed；工具循环 → 逐个 run_tool → 下一轮；
    第 max_rounds 轮仍请求工具 → 收尾请求（不计轮数）→ max_rounds；
    cancel/任务取消 → cancelled（桥接层兜底终态）。
    """
    request = ctx.request
    emitter = ctx.emitter
    cancel = request.cancel

    # ---- ① 配置加载与工具目录（独立短会话）----
    with SessionLocal() as session:
        agent = session.get(AgentEntry, request.agent_id)
        model = session.get(ModelEntry, agent.model_id) if agent is not None else None
        if agent is None or model is None:
            raise AgentUnavailableError("该 Agent 或其绑定的模型已不可用")
        ctx.agent_name = agent.name
        ctx.model_name = model.display_name
        ctx.base_url = model.base_url
        ctx.model_identifier = model.model_identifier
        ctx.api_key = secret_vault.load_secret(session, model.secret_ref)
        ctx.temperature = model.temperature
        ctx.max_tokens = model.max_output_tokens
        agent_system_prompt = agent.system_prompt
        ctx.enable_thinking = bool(agent.enable_deep_thinking and agent.thinking_level != "off")
        catalog, skill_ids = build_tool_catalog(session, request.agent_id, request.limits)
        ctx.skill_catalog_ids = skill_ids
        ctx.max_rounds = agent.max_rounds
        if request.limits.max_rounds is not None:
            ctx.max_rounds = min(agent.max_rounds, request.limits.max_rounds)
        # ---- 011：压缩配置与会话压缩状态 ----
        ctx.available_input = available_input_tokens(
            int(model.context_length), int(model.max_output_tokens or 0),
        )
        ctx.compact_enabled = bool(agent.auto_compact) and request.conversation_id is not None
        ctx.compact_trigger_ratio = float(agent.compact_trigger_ratio or 0.8)
        ctx.compact_keep_recent_rounds = int(agent.compact_keep_recent_rounds or 5)
        ctx.compact_summary_target_tokens = int(agent.compact_summary_target_tokens or 1000)
        ctx.compact_summary, boundary_seq = "", 0
        if request.conversation_id is not None:
            ctx.compact_summary, boundary_seq = load_compaction(session, request.conversation_id)
        ctx.compact_boundary_seq = boundary_seq
    # ---- ② MCP 连接（每运行独享；失败不阻断，R5）----
    mcp_server_ids = sorted({c.server_id for c in catalog if c.server_id is not None})
    with SessionLocal() as mcp_session:
        sessions_map, stacks, tools_by_server = await connect_mcp_servers(mcp_session, mcp_server_ids)
    ctx.mcp_stacks = stacks
    ctx.tool_ctx = ToolContext(
        run_request=request, emitter=emitter, cancel=cancel,
        catalog={c.exposed_name: c for c in catalog},
        skill_catalog_ids=skill_ids,
        mcp_sessions=sessions_map, mcp_stacks=stacks,
    )

    # ---- ③ Skill 目录 XML（澄清指定格式，FR-014）----
    skill_catalog_entries: list[dict[str, str]] = []
    for dir_name in sorted(skill_ids):
        data = skill_files.read_skill(skill_files.skills_root() / dir_name, dir_name)
        skill_catalog_entries.append({
            "id": dir_name,
            "name": data.name if data else dir_name,
            "description": data.description if data else "",
        })

    # ---- ④ 消息组装（FR-016：本条用户消息仅出现一次）----
    system_parts: list[str] = []
    if agent_system_prompt:
        system_parts.append(agent_system_prompt)
    if skill_catalog_entries:
        system_parts.append(build_skill_catalog_section(skill_catalog_entries))
    # ---- ④⑤ 统一上下文构造（ContextBuilder：System+Skills+Summary+History+Input+Tools）----
    boundary = getattr(ctx, "compact_boundary_seq", 0)
    effective_history = [
        item for item in request.history
        if item.seq is None or item.seq > boundary
    ]
    ctx.effective_history = effective_history
    builder = ContextBuilder()
    builder.set_fixed_prefix(system_parts, ctx.compact_summary, summary_role=SUMMARY_ROLE)
    builder.set_history([
        {"role": item.role, "content": item.content} for item in effective_history
    ])
    if request.user_message and not (
        request.history and request.history[-1].role == "user"
        and request.history[-1].content == request.user_message
    ):
        # 直接调用 Runtime（评测）场景：本次输入不在历史中 → 追加一次（FR-016）
        builder.append_current_input(request.user_message)
    builder.set_tools([
        {"type": "function", "function": {
            "name": c.exposed_name,
            "description": c.description or "",
            "parameters": c.parameters,
        }}
        for c in catalog
    ] or None)
    ctx.builder = builder
    ctx.messages = builder.messages  # 同一 list 引用：运行期演化双向可见
    tools_payload = builder.tools_payload

    yield emitter.emit(
        rt_events.EVENT_RUN_STARTED,
        RunStartedData(
            agent_id=request.agent_id,
            agent_name=ctx.agent_name,
            model_name=ctx.model_name,
            model_identifier=ctx.model_identifier,
        ),
        round=0,
    )

    # ---- 首次发送固定内容预检（FR-039）----
    if ctx.compact_enabled or ctx.request.conversation_id is not None:
        async for ev in _maybe_compact(ctx, precheck=True):
            yield ev
        if ctx.capacity_error:
            for ev in _error_out(ctx, "context_overflow", ctx.capacity_error):
                yield ev
            return

    for round_no in range(1, ctx.max_rounds + 1):
        if cancel.is_set():
            yield _completed(ctx, "cancelled", REASON_CANCELLED, stopped=True)
            return
        ctx.round_no = round_no
        # ---- 每轮请求前容量检查（FR-038：运行中的工具结果也可能超限）----
        if ctx.compact_enabled:
            async for ev in _maybe_compact(ctx, precheck=False):
                yield ev
            if ctx.capacity_error:
                for ev in _error_out(ctx, "context_overflow", ctx.capacity_error):
                    yield ev
                return
        async for event in _stream_model_request(ctx, tools_payload):
            yield event
        _merge_usage(ctx)
        if ctx.stream_cancelled or cancel.is_set():
            yield _completed(ctx, "cancelled", REASON_CANCELLED, stopped=True)
            return
        if ctx.stream_error_category is not None:
            for ev in _error_out(ctx, ctx.stream_error_category, ctx.stream_error_text or REASON_ERROR):
                yield ev
            return
        if not ctx.pending_tool_calls:
            if not ctx.content_parts and not ctx.reasoning_parts:
                error_text = _STREAM_ERROR_MESSAGES["empty_response"]
                for ev in _error_out(ctx, "empty_response", error_text):
                    yield ev
                return
            yield _completed(ctx, "completed", REASON_COMPLETED)
            return

        # ---- 工具执行：先 assistant(tool_calls)，后逐个 tool 结果（顺序敏感）----
        tool_calls_payload = []
        tool_messages = []
        for call in ctx.pending_tool_calls:
            call_name = call.get("name", "")
            call_args = call.get("arguments") or "{}"
            with SessionLocal() as tool_session:
                record = await run_tool(call_name, call_args, ctx.tool_ctx, tool_session)
            tool_calls_payload.append({
                "id": call.get("id") or record.call_id,
                "type": "function",
                "function": {"name": call_name, "arguments": call_args},
            })
            yield ctx.emitter.emit(
                rt_events.EVENT_TOOL_CALL_STARTED,
                ToolCallStartedData(
                    round=round_no, call_id=record.call_id,
                    tool_name=record.exposed_name, tool_type=record.tool_type,
                    params_summary=record.params_summary,
                    params=_truncate_for_display(record.params_full, settings.runtime_tool_params_max_chars),
                    display_name=record.display_name or record.exposed_name,
                    server_name=record.server_name,
                    params_full=record.params_full,
                ),
                round=round_no,
                call_id=record.call_id,
            )
            tool_messages.append({
                "role": "tool",
                "tool_call_id": call.get("id") or record.call_id,
                "content": record.result_for_model,
            })
            yield ctx.emitter.emit(
                rt_events.EVENT_TOOL_CALL_COMPLETED,
                ToolCallCompletedData(
                    round=round_no, call_id=record.call_id,
                    tool_name=record.exposed_name, tool_type=record.tool_type,
                    status=record.status,
                    duration_ms=record.duration_ms,
                    result_summary=record.summary,
                    result=_truncate_for_display(record.result_full, settings.runtime_tool_result_max_chars),
                    display_name=record.display_name or record.exposed_name,
                    server_name=record.server_name,
                    result_full=record.result_full,
                ),
                round=round_no, call_id=record.call_id,
            )
        ctx.builder.append_tool_exchange(
            {"role": "assistant", "content": "".join(ctx.content_parts) or None,
             "tool_calls": tool_calls_payload},
            tool_messages,
        )
        if cancel.is_set():
            yield _completed(ctx, "cancelled", REASON_CANCELLED, stopped=True)
            return

    # ---- 轮数耗尽仍请求工具 → 收尾请求（不计轮数，无 tools，FR-012）----
    if ctx.pending_tool_calls:
        ctx.round_no = ctx.max_rounds + 1
        if ctx.compact_enabled:
            async for ev in _maybe_compact(ctx, precheck=False):
                yield ev
            if ctx.capacity_error:
                for ev in _error_out(ctx, "context_overflow", ctx.capacity_error):
                    yield ev
                return
        async for event in _stream_model_request(ctx, None):
            yield event
        _merge_usage(ctx)
        if ctx.stream_cancelled or cancel.is_set():
            yield _completed(ctx, "cancelled", REASON_CANCELLED, stopped=True)
            return
        if ctx.stream_error_category is not None:
            for ev in _error_out(ctx, ctx.stream_error_category, ctx.stream_error_text or REASON_ERROR):
                yield ev
            return
        yield _completed(ctx, "max_rounds", REASON_MAX_ROUNDS)
        return
    yield _completed(ctx, "completed", REASON_COMPLETED)

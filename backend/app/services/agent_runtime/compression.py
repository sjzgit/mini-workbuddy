"""上下文容量估算与自动压缩（specs/011 FR-022~042；research R1~R6）。

估算口径（R1）：ceil(chars × 0.6) + 每条消息 4 token 结构开销；
可用输入容量（R2）：context_length − 输出预留 − 安全余量。
压缩以完整消息组为单位（工具请求与结果同组同裁，FR-036）；
摘要与边界单事务写回（FR-034）；失败转备用裁剪且不推进边界（FR-040/041）。
"""

import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import ConversationCompactionEntry
from app.schemas.agent_runtime import (
    EVENT_COMPRESSION_COMPLETED,
    EVENT_COMPRESSION_FAILED,
    EVENT_COMPRESSION_FALLBACK,
    EVENT_COMPRESSION_STARTED,
    CompressionCompletedData,
    CompressionFailedData,
    CompressionFallbackData,
    CompressionStartedData,
    ModelRequestCompletedData,
    ModelRequestStartedData,
)
from app.services.agent_runtime.compression_prompt import (
    build_summary_prompt,
    extract_summary_text,
    format_group_text,
    SUMMARY_ROLE,
)
from app.services.agent_runtime import events as rt_events
from app.services.openai_client import (
    ChatHttpError,
    ContentDelta,
    ReasoningDelta,
    UsageInfo,
    stream_chat_completion,
)

if TYPE_CHECKING:
    from app.services.agent_runtime.runtime import RunContext

logger = logging.getLogger(__name__)

# 每条消息结构开销（原 chat_service 口径，011 起单点化于此）
CONTEXT_MSG_OVERHEAD = 4


def estimate_text_tokens(text: str) -> int:
    """字符级 token 估算（估算口径，FR-024：与实际用量严格区分并标注）。"""
    from app.schemas.chat import CONTEXT_CHAR_TOKEN_RATIO

    if not text:
        return 0
    return math.ceil(len(text) * CONTEXT_CHAR_TOKEN_RATIO)


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """消息数组估算：每条 content + tool_calls 文本 + 结构开销。"""
    total = 0
    for message in messages:
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls")
        extra = json.dumps(tool_calls, ensure_ascii=False) if tool_calls else ""
        total += estimate_text_tokens(content) + estimate_text_tokens(extra)
        total += CONTEXT_MSG_OVERHEAD
    return total


def available_input_tokens(context_length: int, max_output_tokens: int | None) -> int:
    """可用输入容量 = 上下文长度 − 输出预留 − 安全余量（R2，FR-023）。"""
    reserve = max_output_tokens if (max_output_tokens and max_output_tokens > 0) else settings.compact_default_output_reserve_tokens
    safety = math.ceil(context_length * settings.compact_safety_margin_ratio)
    return max(0, context_length - reserve - safety)


@dataclass
class ContextGroup:
    """一组完整消息：user 单条一组；assistant 及其后全部 tool 结果一组（FR-036）。"""

    messages: list[dict[str, Any]] = field(default_factory=list)
    db_seq: int | None = None  # 组内最大 messages.seq；None = 运行内新增组

    @property
    def tokens(self) -> int:
        return estimate_messages_tokens(self.messages)


def build_context_groups(ctx: "RunContext") -> list[ContextGroup]:
    """把 ctx.messages 划分为有序消息组。

    前缀（system + 已有摘要）不参与分组；历史消息按 request.history 的
    seq 标注归属；运行内新增消息（工具交互、跨轮正文）成组但 db_seq=None。
    """
    prefix_len = ctx.builder.prefix_len if ctx.builder is not None else 0
    history = getattr(ctx, "effective_history", None) or ctx.request.history
    groups: list[ContextGroup] = []
    current: ContextGroup | None = None
    hist_index = 0
    for index, message in enumerate(ctx.messages):
        if index < prefix_len:
            continue
        seq: int | None = None
        if hist_index < len(history):
            seq = history[hist_index].seq
            hist_index += 1
        role = message.get("role")
        if role == "user" or current is None:
            current = ContextGroup(messages=[message], db_seq=seq)
            groups.append(current)
        else:
            current.messages.append(message)
            if seq is not None:
                current.db_seq = max(current.db_seq or 0, seq)
    return groups


# ---- 异常与用量工具 ----


class CompressionError(Exception):
    """压缩摘要失败（reason ∈ timeout/model_error/empty_summary）。"""


class CompressionCancelled(Exception):
    """压缩过程中收到取消信号（FR-042）。"""


def _usage_model(usage: dict | None):
    from app.schemas.agent_runtime import UsageInfo

    if usage is None:
        return None
    return UsageInfo(
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
    )


# ---- 摘要请求（压缩用模型调用，purpose=context_compression，FR-045）----

async def _run_summary_request(
    ctx: "RunContext",
    prompt: str,
    events_out: list,
) -> tuple[str, dict | None, int]:
    """一次压缩摘要请求（R5.4）：产出 started/completed 事件（purpose 标记用途，
    计入模型调用统计 FR-045）；流式收集全文，delta 不外发、不进正文缓冲。

    返回 (摘要全文, usage dict | None, 耗时 ms)。
    超时/模型错误/空摘要以 CompressionError 抛出，取消以 CompressionCancelled 抛出。
    """
    call_id = ctx.emitter.next_call_id("c")
    messages = [{"role": SUMMARY_ROLE, "content": prompt}]
    started_at = time.monotonic()
    events_out.append(ctx.emitter.emit(
        rt_events.EVENT_MODEL_REQUEST_STARTED,
        ModelRequestStartedData(round=ctx.round_no, call_id=call_id, purpose="context_compression"),
        round=ctx.round_no, call_id=call_id,
    ))
    parts: list[str] = []
    usage: dict | None = None
    import httpx

    try:
        async for delta in stream_chat_completion(
            ctx.base_url, ctx.model_identifier, ctx.api_key,
            messages,
            temperature=ctx.temperature,
            max_tokens=ctx.max_tokens,
            enable_thinking=False,
            tools=None,
            include_usage=True,
            read_timeout_seconds=settings.compact_request_timeout_seconds,
        ):
            if ctx.request.cancel.is_set():
                raise CompressionCancelled()
            if isinstance(delta, ContentDelta):
                parts.append(delta.text)
            elif isinstance(delta, ReasoningDelta):
                pass  # 思考增量不进入摘要
            elif isinstance(delta, UsageInfo):
                usage = {
                    "prompt_tokens": delta.prompt_tokens,
                    "completion_tokens": delta.completion_tokens,
                    "total_tokens": delta.total_tokens,
                }
    except CompressionCancelled:
        raise
    except ChatHttpError as exc:
        raise CompressionError(f"model_error:{exc.status_code}") from exc
    except httpx.TimeoutException as exc:
        raise CompressionError("timeout") from exc
    except httpx.HTTPError as exc:
        raise CompressionError("model_error") from exc
    duration_ms = int((time.monotonic() - started_at) * 1000)
    text = extract_summary_text("".join(parts))
    if not text:
        raise CompressionError("empty_summary")
    events_out.append(ctx.emitter.emit(
        rt_events.EVENT_MODEL_REQUEST_COMPLETED,
        ModelRequestCompletedData(
            round=ctx.round_no, call_id=call_id, status="ok",
            duration_ms=duration_ms,
            usage=_usage_model(usage),
            purpose="context_compression",
            request_messages=messages,
            output_content=text,
        ),
        round=ctx.round_no, call_id=call_id,
    ))
    return text, usage, duration_ms


# ---- 压缩编排（R5；事件经 yield 交回 Runtime 主循环）----


def _split_batches(group_texts: list[str], budget_tokens: int) -> list[list[int]]:
    """按组切批：单批累计估算不超过 budget（FR-032：按完整组分批，不递归）。"""
    batches: list[list[int]] = []
    current: list[int] = []
    current_tokens = 0
    for index, text in enumerate(group_texts):
        tokens = estimate_text_tokens(text)
        if current and current_tokens + tokens > budget_tokens:
            batches.append(current)
            current = []
            current_tokens = 0
        current.append(index)
        current_tokens += tokens
    if current:
        batches.append(current)
    return batches[: settings.compact_max_batches]


def load_compaction(session, conversation_id: int) -> tuple[str, int]:
    """读取会话压缩状态；(summary, boundary_seq)，无记录返回 ("", 0)。"""
    row = session.scalar(
        select(ConversationCompactionEntry).where(
            ConversationCompactionEntry.conversation_id == conversation_id
        )
    )
    if row is None:
        return ("", 0)
    return (row.summary_text or "", row.boundary_seq or 0)


def persist_compaction(conversation_id: int, summary_text: str, boundary_seq: int) -> None:
    """单事务 upsert 压缩状态（摘要与边界一致更新，FR-033/034）；失败抛异常。"""
    with SessionLocal() as session:
        row = session.scalar(
            select(ConversationCompactionEntry).where(
                ConversationCompactionEntry.conversation_id == conversation_id
            )
        )
        if row is None:
            session.add(ConversationCompactionEntry(
                conversation_id=conversation_id,
                summary_text=summary_text,
                boundary_seq=boundary_seq,
            ))
        else:
            row.summary_text = summary_text
            row.boundary_seq = boundary_seq
        session.commit()


async def run_compaction(ctx: "RunContext", *, trigger_reason: str):
    """一次完整压缩尝试（async generator，产出契约 §1 压缩事件）。

    成功：摘要与边界写回、ctx.messages 重写（保留最近配置轮数 + 本次消息 +
    运行内新增组），压缩后重估仍超限则逐步减少保留组（FR-037）。
    失败：compression_failed → 备用裁剪（compression_fallback），不写库不推边界
    （FR-040/041）；取消：compression_failed(cancelled)。
    判定结果写入 ctx.compaction_ok（True=成功 / False=失败或取消）。
    """
    ctx.compact_attempts += 1
    ctx.compaction_ok = False
    attempt_call_id = ctx.emitter.next_call_id("k")  # 压缩尝试标识（载荷关联键，多次尝试不冲突）
    started_mono = time.monotonic()
    estimated_before = estimate_messages_tokens(ctx.messages)
    available = ctx.available_input
    trigger_ratio = float(ctx.compact_trigger_ratio)

    groups = build_context_groups(ctx)
    db_indices = [i for i, g in enumerate(groups) if g.db_seq is not None]
    keep_rounds = max(1, int(ctx.compact_keep_recent_rounds))
    if len(db_indices) <= keep_rounds:
        return  # 没有可压缩的较早对话

    cut = db_indices[-keep_rounds]
    compressed = groups[:cut]
    kept = groups[cut:]
    if not compressed:
        return

    group_texts = [format_group_text_local(g.messages) for g in compressed]
    effective_target = min(
        int(ctx.compact_summary_target_tokens), max(available // 2, 100),
    )

    started_event = ctx.emitter.emit(
        EVENT_COMPRESSION_STARTED,
        CompressionStartedData(
            trigger_reason=trigger_reason,
            estimated_input_tokens=estimated_before,
            available_input_tokens=available,
            trigger_ratio=trigger_ratio,
            input_full=build_summary_prompt(
                ctx.compact_summary, group_texts, target_tokens=effective_target,
            ),
        ),
        round=ctx.round_no, call_id=attempt_call_id,
    )
    yield started_event

    try:
        budget = max(available // 2, 500)
        batches = _split_batches(group_texts, budget)
        summary_text = ctx.compact_summary
        batch_count = 0
        for batch in batches:
            batch_texts = [group_texts[i] for i in batch]
            prompt = build_summary_prompt(
                summary_text, batch_texts, target_tokens=effective_target,
            )
            events_out: list = []
            text, usage, _dur = await _run_summary_request(ctx, prompt, events_out)
            for ev in events_out:
                yield ev
            if usage is not None:
                incoming = _usage_model(usage)
                ctx.usage_total = (
                    incoming if ctx.usage_total is None
                    else ctx.usage_total.merge_add(incoming)
                )
            summary_text = text
            batch_count += 1
        if not batch_count:
            raise CompressionError("empty_summary")

        boundary_seq = max(
            (g.db_seq for g in compressed if g.db_seq is not None), default=0,
        )
        persist_compaction(ctx.request.conversation_id, summary_text, boundary_seq)

        # 重写上下文（ContextBuilder 统一负责）：前缀 + 新摘要 + 保留组
        kept_messages = [m for g in kept for m in g.messages]
        ctx.builder.apply_compaction(summary_text, kept_messages, summary_role=SUMMARY_ROLE)
        ctx.compact_summary = summary_text

        # 压缩后重估仍超限 → 逐步减少较早保留组（FR-037），记录实际保留数
        dropped_extra = 0
        while (
            len(kept) > 1
            and estimate_messages_tokens(ctx.messages) > available
        ):
            removed = kept.pop(0)
            kept_messages = [m for g in kept for m in g.messages]
            ctx.builder.apply_compaction(summary_text, kept_messages, summary_role=SUMMARY_ROLE)
            dropped_extra += 1
        estimated_after = estimate_messages_tokens(ctx.messages)
        kept_rounds_actual = sum(1 for g in kept if g.db_seq is not None)

        yield ctx.emitter.emit(
            EVENT_COMPRESSION_COMPLETED,
            CompressionCompletedData(
                estimated_tokens_before=estimated_before,
                estimated_tokens_after=estimated_after,
                messages_compressed=sum(len(g.messages) for g in compressed),
                groups_compressed=len(compressed),
                kept_rounds=kept_rounds_actual,
                summary_estimated_tokens=estimate_text_tokens(summary_text),
                batches=batch_count,
                duration_ms=int((time.monotonic() - started_mono) * 1000),
                boundary_seq=boundary_seq,
                output_full=summary_text,
            ),
            round=ctx.round_no, call_id=attempt_call_id,
        )
        ctx.compaction_ok = True
        ctx.compact_done_round = ctx.round_no + 1  # 覆盖下一轮的开始检查（预检后立即可用）
        return
    except CompressionCancelled:
        yield ctx.emitter.emit(
            EVENT_COMPRESSION_FAILED,
            CompressionFailedData(
                reason="cancelled",
                estimated_tokens_before=estimated_before,
                duration_ms=int((time.monotonic() - started_mono) * 1000),
            ),
            round=ctx.round_no, call_id=attempt_call_id,
        )
        return
    except CompressionError as exc:
        reason = str(exc).split(":")[0]
        yield ctx.emitter.emit(
            EVENT_COMPRESSION_FAILED,
            CompressionFailedData(
                reason=reason if reason in ("timeout", "model_error", "empty_summary", "save_failed") else "model_error",
                estimated_tokens_before=estimated_before,
                duration_ms=int((time.monotonic() - started_mono) * 1000),
            ),
            round=ctx.round_no, call_id=attempt_call_id,
        )
    except Exception:  # noqa: BLE001 — 写回/组装未知异常按失败降级（FR-040）
        logger.exception("[compact] 未预期异常 conversation=%s", ctx.request.conversation_id)
        yield ctx.emitter.emit(
            EVENT_COMPRESSION_FAILED,
            CompressionFailedData(
                reason="save_failed",
                estimated_tokens_before=estimated_before,
                duration_ms=int((time.monotonic() - started_mono) * 1000),
            ),
            round=ctx.round_no, call_id=attempt_call_id,
        )

    # ---- 备用裁剪（FR-040/041）：只影响本次请求，不写库、不推边界 ----
    kept_now = [g for g in kept]
    dropped = 0
    while len(kept_now) > 1:
        kept_messages = [m for g in kept_now for m in g.messages]
        candidate = ctx.builder.prefix() + kept_messages
        if estimate_messages_tokens(candidate) <= available:
            break
        removed = kept_now.pop(0)  # 从最早开始按完整组丢弃
        dropped += 1
        del removed
    kept_messages = [m for g in kept_now for m in g.messages]
    # 保留既有摘要（不推进边界）：以原摘要重写前缀 + 保留消息
    ctx.builder.apply_compaction(ctx.builder.summary_text, kept_messages, summary_role=SUMMARY_ROLE)
    yield ctx.emitter.emit(
        EVENT_COMPRESSION_FALLBACK,
        CompressionFallbackData(
            reason="摘要生成失败，已按完整消息组裁剪较早对话（不影响保存的历史与压缩边界）",
            dropped_groups=dropped,
            kept_groups=len(kept_now),
            estimated_tokens_after=estimate_messages_tokens(ctx.messages),
        ),
        round=ctx.round_no, call_id=attempt_call_id,
    )


def format_group_text_local(group_messages: list[dict]) -> str:
    """组文本渲染（代理到 compression_prompt，保持模块内调用简短）。"""
    return format_group_text(group_messages)


# ---- 容量检查入口（Runtime 每轮请求前调用，FR-038/039）----

# 未开启压缩时的超限提示（FR-027：明确指引，不静默丢弃）
OVERFLOW_CLOSED_MESSAGE = (
    "会话上下文已超出该模型可用的容量（未开启自动压缩）。"
    "请缩短输入、在 Agent 管理中开启自动压缩，或新建会话。"
)
# 已开启压缩但压缩与备用裁剪后仍超限（FR-039/041）
OVERFLOW_OPEN_MESSAGE = (
    "会话上下文已超出该模型可用的容量，压缩后仍无法容纳必要内容。"
    "请减少系统提示词/工具配置，或缩短输入。"
)


async def _maybe_compact(ctx: "RunContext", *, precheck: bool):
    """容量检查并在需要时执行压缩（async generator，产出压缩事件）。

    ctx.capacity_error 置为终态错误文案（None = 可继续）。
    precheck=True：固定内容预检（达到可用容量即触发，FR-039）；
    precheck=False：触发比例检查（FR-038）。
    """
    ctx.capacity_error = None
    if ctx.compact_done_round == ctx.round_no and not precheck:
        return  # 本轮已成功压缩，避免同轮重复触发
    if not ctx.compact_enabled:
        if estimate_messages_tokens(ctx.messages) > ctx.available_input:
            ctx.capacity_error = OVERFLOW_CLOSED_MESSAGE
        return
    estimated = estimate_messages_tokens(ctx.messages)
    threshold = ctx.available_input if precheck else ctx.compact_trigger_ratio * ctx.available_input
    if estimated < threshold:
        return
    if ctx.compact_attempts >= settings.compact_max_attempts_per_run:
        # 尝试次数耗尽（R5.8）：不再请求摘要；装得下就继续，装不下明确报错
        if estimated > ctx.available_input:
            ctx.capacity_error = OVERFLOW_OPEN_MESSAGE
        return
    async for event in run_compaction(
        ctx, trigger_reason="precheck" if precheck else "threshold",
    ):
        yield event
    if not ctx.compaction_ok and estimate_messages_tokens(ctx.messages) > ctx.available_input:
        ctx.capacity_error = OVERFLOW_OPEN_MESSAGE

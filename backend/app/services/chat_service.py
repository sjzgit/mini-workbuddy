"""聊天业务逻辑：会话/消息持久化（specs/008-chat-conversations）。

契约主定义：specs/008-chat-conversations/contracts/chat-api.md
本段为第一部分：导入、常量与异常类。
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from math import ceil

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import secret_vault
from app.core.db import SessionLocal
from app.models import AgentEntry, ConversationEntry, MessageEntry, ModelEntry
from app.schemas.chat import (
    CONTEXT_OVERFLOW_DETAIL,
    STREAM_PING_INTERVAL_SECONDS,
    TITLE_DEFAULT,
    TITLE_MAX_CHARS,
    ContentDeltaData,
    DoneEventData,
    ErrorEventData,
    MessageOut,
    ReasoningDeltaData,
    SendMessageRequest,
    StartReplyResponse,
    ConversationSummary,
)
from app.services.generation_registry import (
    EVENT_CONTENT,
    EVENT_DONE,
    EVENT_ERROR,
    EVENT_REASONING,
    StreamEvent,
    GenerationTask,
    get_registry,
)
from app.schemas.agent_runtime import RunCompletedData
from app.services.agent_runtime import RunHistoryMessage, RunLimits, RunRequest, execute_run
from app.services.agent_runtime import events as runtime_event_names

logger = logging.getLogger(__name__)

# 每条消息的 token 开销系数粗估（role 包裹开销，research R3）
_CONTEXT_MSG_OVERHEAD = 4

# 契约错误文案（路由层/流内原样展示，FR-023）
MSG_AGENT_UNAVAILABLE = "该 Agent 已不可用，请重新选择 Agent"
MSG_CONVERSATION_BUSY = "当前会话正在生成回复，请等待完成或先停止生成"
MSG_REGENERATE_INVALID = "仅最后一条 Agent 回复可以重新生成"
MSG_SESSION_LOST = "生成任务因服务重启而中断，该回复未完成"

# 流内错误文案（契约 StreamErrorCategory → 人话说明，FR-023）
_STREAM_ERROR_MESSAGES: dict[str, str] = {
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


class ConversationNotFoundError(LookupError):
    """会话不存在（路由层转 404）。"""


class MessageNotFoundError(LookupError):
    """消息不存在（路由层转 404）。"""


class AgentUnavailableError(ValueError):
    """会话指定的 Agent 不存在/不可用（路由层转 400）。"""


class ConversationBusyError(ValueError):
    """会话正在生成回复（发送/切换/重新生成都转 409，FR-020）。"""


class ContextOverflowError(ValueError):
    """上下文超限（路由层转 422，文案见契约 CONTEXT_OVERFLOW_DETAIL）。"""


class RegenerateInvalidError(ValueError):
    """重新生成对象非法（路由层转 409）。"""


def _utcnow() -> datetime:
    """与 models._utcnow 同口径：naive UTC、去微秒。"""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _to_summary(entry: ConversationEntry) -> ConversationSummary:
    return ConversationSummary(
        id=entry.id,
        title=entry.title,
        agent_id=entry.agent_id,
        updated_at=entry.updated_at.isoformat(),
        created_at=entry.created_at.isoformat(),
    )


def _to_message_out(entry: MessageEntry) -> MessageOut:
    return MessageOut(
        id=entry.id,
        conversation_id=entry.conversation_id,
        role=entry.role,
        agent_id=entry.agent_id,
        agent_name=entry.agent_name,
        reasoning_content=entry.reasoning_content,
        content=entry.content,
        status=entry.status,
        seq=entry.seq,
        created_at=entry.created_at.isoformat(),
    )


def _estimate_tokens(text: str) -> int:
    """字符级 token 估算（research R3：ceil(chars × 0.6)）。"""
    return ceil(len(text) * 0.6)


def _estimate_context_tokens(messages: list[dict[str, str]], system: str) -> int:
    """上下文总 token 估算：system + 每条消息（content + role 开销）。"""
    total = ceil(len(system) * 0.6)
    for message in messages:
        total += _estimate_tokens(message["content"]) + _CONTEXT_MSG_OVERHEAD
    return total


def _get_or_404(session: Session, conversation_id: int) -> ConversationEntry:
    """取会话或抛 ConversationNotFoundError（路由层转 404）。"""
    entry = session.get(ConversationEntry, conversation_id)
    if entry is None:
        raise ConversationNotFoundError(f"会话 {conversation_id} 不存在")
    return entry


def _last_message(session: Session, conversation_id: int) -> MessageEntry | None:
    """seq 最大的消息（重新生成的前置判断）。"""
    return session.scalar(
        select(MessageEntry)
        .where(MessageEntry.conversation_id == conversation_id)
        .order_by(MessageEntry.seq.desc())
        .limit(1)
    )


def _effective_history(session: Session, conversation_id: int) -> list[MessageEntry]:
    """有效历史 = 全部 user + status=completed 的 assistant（FR-017）。"""
    return list(
        session.scalars(
            select(MessageEntry)
            .where(
                MessageEntry.conversation_id == conversation_id,
                (MessageEntry.role == "user")
                | (
                    (MessageEntry.role == "assistant")
                    & (MessageEntry.status == "completed")
                ),
            )
            .order_by(MessageEntry.seq)
        ).all()
    )




def _build_llm_messages(
    session: Session,
    conversation: ConversationEntry,
    agent: AgentEntry,
) -> list[dict[str, str]]:
    """组装 LLM 请求消息数组（research R2/R3）。

    [system?] + 有效历史（content only，seq 升序）；本次用户消息已先落库，
    自然位于末尾且仅出现一次（FR-016）。system 取当前 Agent 的 system_prompt，
    为空则不设 system 消息。
    """
    messages: list[dict[str, str]] = []
    if agent.system_prompt.strip():
        messages.append({"role": "system", "content": agent.system_prompt})
    for entry in _effective_history(session, conversation.id):
        messages.append({"role": entry.role, "content": entry.content})
    return messages



# ---- 会话与消息查询（契约端点实现，路由层调用）----


def create_conversation(session: Session, agent_id: int) -> ConversationSummary:
    """新建会话（标题"新会话"；Agent 必须存在，否则 AgentUnavailableError→400）。"""
    agent = session.get(AgentEntry, agent_id)
    if agent is None:
        raise AgentUnavailableError(MSG_AGENT_UNAVAILABLE)
    entry = ConversationEntry(title=TITLE_DEFAULT, agent_id=agent_id)
    session.add(entry)
    session.commit()
    return _to_summary(entry)


def list_conversations(session: Session) -> list[ConversationSummary]:
    """会话列表（只返回摘要，updated_at 倒序、id 倒序并列稳定；FR-005/006）。"""
    entries = session.scalars(
        select(ConversationEntry)
        .order_by(ConversationEntry.updated_at.desc(), ConversationEntry.id.desc())
    ).all()
    return [_to_summary(entry) for entry in entries]


def get_messages(session: Session, conversation_id: int) -> list[MessageOut]:
    """会话消息（seq 升序）。"""
    _get_or_404(session, conversation_id)
    entries = session.scalars(
        select(MessageEntry)
        .where(MessageEntry.conversation_id == conversation_id)
        .order_by(MessageEntry.seq)
    ).all()
    return [_to_message_out(entry) for entry in entries]



# ---- 发送消息（T010/T011）----


def _resolve_generation_inputs(
    session: Session, conversation: ConversationEntry,
) -> tuple[AgentEntry, ModelEntry, str | None]:
    """解析生成所需的 Agent/模型/密钥（不可用即 AgentUnavailableError）。"""
    agent = session.get(AgentEntry, conversation.agent_id)
    if agent is None:
        raise AgentUnavailableError(MSG_AGENT_UNAVAILABLE)
    model = session.get(ModelEntry, agent.model_id)
    if model is None:
        raise AgentUnavailableError("该 Agent 绑定的模型已不可用，请重新选择 Agent")
    api_key = secret_vault.load_secret(session, model.secret_ref)
    return agent, model, api_key



def _mark_orphan_incomplete(session: Session, conversation_id: int) -> None:
    """把本会话孤儿 generating 占位行标记为 incomplete（进程重启后惰性清理）。"""
    placeholders = session.scalars(
        select(MessageEntry)
        .where(
            MessageEntry.conversation_id == conversation_id,
            MessageEntry.status == "generating",
        )
    ).all()
    for entry in placeholders:
        entry.status = "incomplete"
        entry.content = entry.content or ""
    if placeholders:
        session.commit()



async def _run_generation(
    conversation_id: int,
    reply_message_id: int,
    agent_id: int,
    cancel_event: "asyncio.Event | None" = None,
    run_id: str = "",
) -> None:
    """生成任务主体（009 桥接，FR-004）：构造 RunRequest → 消费 execute_run 事件 → 终态落库。

    Runtime 负责模型调用与工具循环；本函数只做事件转发与持久化：
    reasoning/content 增量直通 SSE 通道（契约 delta 负载）；run_completed 按
    data-model §2.2 映射落库并合成终态事件。
    """
    registry = get_registry()
    task = registry.get(reply_message_id)
    if task is None:
        return
    from app.schemas.agent_runtime import RunCompletedData

    # 有效历史（FR-017）：user 全部 + completed assistant，seq 升序
    with SessionLocal() as session:
        history_rows = _effective_history(session, conversation_id)
        history = [RunHistoryMessage(role=row.role, content=row.content) for row in history_rows]

    request = RunRequest(
        agent_id=agent_id,
        user_message="",  # 本次用户消息已是 history 末位（落库后读取，仅出现一次 FR-016）
        history=history,
        limits=RunLimits(),
        cancel=cancel_event or asyncio.Event(),
        run_id=run_id,
    )
    stopped = False
    error_category: str | None = None
    error_text: str | None = None
    completed: "RunCompletedData | None" = None
    content_buffer: list[str] = []
    reasoning_buffer: list[str] = []
    try:
        async for event in execute_run(request):
            if event.event == runtime_event_names.EVENT_REASONING_DELTA:
                task.publish(StreamEvent(
                    event=EVENT_REASONING,
                    data=json.dumps({
                        "run_id": event.run_id, "seq": event.seq,
                        "round": event.data.get("round", 0),
                        "call_id": event.data.get("call_id", ""),
                        "text": event.data.get("text", ""),
                    }, ensure_ascii=False),
                ))
                reasoning_buffer.append(str(event.data.get("text", "")))
            elif event.event == runtime_event_names.EVENT_CONTENT_DELTA:
                task.publish(StreamEvent(
                    event=EVENT_CONTENT,
                    data=json.dumps({
                        "run_id": event.run_id, "seq": event.seq,
                        "round": event.data.get("round", 0),
                        "call_id": event.data.get("call_id", ""),
                        "text": event.data.get("text", ""),
                    }, ensure_ascii=False),
                ))
                content_buffer.append(str(event.data.get("text", "")))
            elif event.event in (
                runtime_event_names.EVENT_RUN_STARTED,
                runtime_event_names.EVENT_TOOL_CALL_STARTED,
                runtime_event_names.EVENT_TOOL_CALL_COMPLETED,
            ):
                # 工具事件按契约 §3 原样转发（run_id/seq/round/call_id/工具名/类型/摘要）
                task.publish(StreamEvent(
                    event=event.event,
                    data=json.dumps(event.data, ensure_ascii=False),
                ))
            elif event.event == runtime_event_names.EVENT_ERROR:
                error_category = str(event.data.get("category", "unknown"))
                error_text = str(event.data.get("message", ""))
            elif event.event == runtime_event_names.EVENT_RUN_COMPLETED:
                completed = RunCompletedData.model_validate(event.data)
    except asyncio.CancelledError:
        stopped = True
    except Exception:  # noqa: BLE001 — 桥接层兜底终态（FR-035）
        logger.exception("runtime 桥接异常 conversation=%s", conversation_id)
        error_category = error_category or "unknown"
        error_text = error_text or _STREAM_ERROR_MESSAGES["unknown"]

    await _finalize_generation(
        conversation_id, reply_message_id, completed,
        stopped=stopped,
        error_category=error_category, error_text=error_text,
        fallback_content="".join(content_buffer),
        fallback_reasoning="".join(reasoning_buffer) or None,
    )


async def _finalize_generation(
    conversation_id: int,
    reply_message_id: int,
    completed: "RunCompletedData | None",
    *,
    stopped: bool,
    error_category: str | None,
    error_text: str | None,
    fallback_content: str = "",
    fallback_reasoning: str | None = None,
) -> None:
    """终态处理（009 data-model §2.2）：completed/max_rounds → completed；
    error/cancelled 有缓冲 → incomplete；无任何正文 → 删占位行（FR-024）。
    错误文本永不写入 content（FR-023）。终态后注册表移除（会话互斥放行）。
    """
    registry = get_registry()
    task = registry.get(reply_message_id)
    if task is None:
        return

    # 任务被硬取消等场景 completed 为 None：以桥接层累积缓冲兜底（保留已生成部分，FR-024）
    status_value = completed.status if completed is not None else "error"
    content_text = completed.content_text if completed is not None else fallback_content
    reasoning_text = (completed.reasoning_text if completed is not None else fallback_reasoning)
    is_ok = status_value in ("completed", "max_rounds")
    has_buffer = bool(content_text) or bool(reasoning_text)

    final = None
    with SessionLocal() as session:
        reply = session.get(MessageEntry, reply_message_id)
        if reply is None:
            registry.remove(reply_message_id)
        else:
            if not has_buffer:
                session.delete(reply)  # 无正文不产生空白回复（FR-024）
            else:
                reply.reasoning_content = reasoning_text or None
                reply.content = content_text
                reply.status = "completed" if is_ok else "incomplete"
                final = _to_message_out(reply)
            conversation = session.get(ConversationEntry, conversation_id)
            if conversation is not None:
                conversation.updated_at = _utcnow()
            session.commit()

    usage_total = completed.usage_total if completed is not None else None
    if error_category is not None:
        task.publish(StreamEvent(
            event=EVENT_ERROR,
            data=ErrorEventData(category=error_category, message=error_text or "").model_dump_json(),
        ))
    if final is None:
        done = StreamEvent(
            event=EVENT_DONE,
            data=json.dumps({
                "run_id": task.run_id or "", "seq": 0,
                "status": "error" if error_category else "cancelled",
                "reason": error_text or "",
                "usage_total": None, "message": None,
                "stopped": stopped,
            }, ensure_ascii=False),
        )
        task.finish(done, stopped=stopped)
        registry.remove(reply_message_id)  # 占位行已删，无终态消息：先广播后清理
        return
    reason_text = error_text or (completed.reason if completed is not None else "")
    done = StreamEvent(
        event=EVENT_DONE,
        data=json.dumps({
            "run_id": task.run_id or "", "seq": 0,
            "status": ("error" if error_category is not None and not is_ok else status_value),
            "reason": reason_text,
            "usage_total": usage_total.model_dump() if usage_total is not None else None,
            "message": final.model_dump(),
            "stopped": stopped or bool(completed and completed.stopped),
        }, ensure_ascii=False),
    )
    task.finish(done, stopped=done_data_stopped(stopped, completed))


def done_data_stopped(stopped: bool, completed) -> bool:
    """合成终态的 stopped 标志（用户停止 或 runtime 判定取消）。"""
    return stopped or bool(completed is not None and completed.stopped)


def send_message(
    session: Session, conversation_id: int, payload: SendMessageRequest,
) -> StartReplyResponse:
    """发送消息：校验 → 落库 → 启动生成（契约 POST /messages 语义）。"""
    conversation = _get_or_404(session, conversation_id)
    _assert_not_busy(session, conversation_id)
    agent, _model, _api_key = _resolve_generation_inputs(session, conversation)
    _assert_context_fits(session, conversation, agent, extra_content=payload.content)
    seq = _next_seq(session, conversation_id)
    user_row = MessageEntry(
        conversation_id=conversation_id,
        role="user",
        content=payload.content,
        status="completed",
        seq=seq,
    )
    reply_row = MessageEntry(
        conversation_id=conversation_id,
        role="assistant",
        agent_id=agent.id,
        agent_name=agent.name,
        content="",
        status="generating",
        seq=seq + 1,
    )
    session.add(user_row)
    session.add(reply_row)
    session.flush()
    if conversation.title == TITLE_DEFAULT:
        conversation.title = _derive_title(payload.content)
    conversation.agent_id = agent.id
    conversation.updated_at = _utcnow()
    session.commit()
    _start_generation_task(conversation_id, reply_row.id, agent.id)
    return StartReplyResponse(
        user_message=_to_message_out(user_row),
        reply_message_id=reply_row.id,
        conversation=_to_summary(conversation),
    )



def _start_generation_task(
    conversation_id: int, reply_message_id: int, agent_id: int,
) -> None:
    """创建 GenerationTask（含 run_id/cancel_event）并启动 asyncio 桥接任务。"""
    registry = get_registry()
    import uuid as _uuid

    run_id = _uuid.uuid4().hex
    gen_task = GenerationTask(
        conversation_id=conversation_id, reply_message_id=reply_message_id,
        run_id=run_id,
    )
    registry.register(gen_task)
    gen_task.async_task = asyncio.get_event_loop().create_task(
        _run_generation(conversation_id, reply_message_id, agent_id,
                        cancel_event=gen_task.cancel_event, run_id=run_id)
    )



def _next_seq(session: Session, conversation_id: int) -> int:
    """会话内下一个顺序号（data-model §5）。"""
    current = session.scalar(
        select(func.max(MessageEntry.seq))
        .where(MessageEntry.conversation_id == conversation_id)
    )
    return (current or 0) + 1


def _derive_title(content: str) -> str:
    """标题截取：前 20 字符，换行折叠空格，截断补省略号（research R7）。"""
    collapsed = " ".join(content.split())
    if len(collapsed) <= TITLE_MAX_CHARS:
        return collapsed
    return collapsed[:TITLE_MAX_CHARS] + "…"


def _assert_not_busy(session: Session, conversation_id: int) -> None:
    """会话生成互斥检查（FR-020）：注册表反查 + 孤儿占位行兜底。"""
    registry = get_registry()
    if registry.get_running_by_conversation(conversation_id) is not None:
        raise ConversationBusyError(MSG_CONVERSATION_BUSY)
    orphan = session.scalar(
        select(MessageEntry)
        .where(
            MessageEntry.conversation_id == conversation_id,
            MessageEntry.status == "generating",
        )
        .limit(1)
    )
    if orphan is not None:
        # 注册表无此任务（进程重启残留）：惰性标 incomplete 后放行
        orphan.status = "incomplete"
        session.commit()



def _assert_context_fits(
    session: Session,
    conversation: ConversationEntry,
    agent: AgentEntry,
    extra_content: str = "",
) -> None:
    """前置容量拦截（FR-018，research R3）；误放行由服务商 400 兜底分类。

    extra_content 为待落库的本条用户消息（估算时需计入）。
    """
    model = session.get(ModelEntry, agent.model_id)
    if model is None:
        raise AgentUnavailableError("该 Agent 绑定的模型已不可用，请重新选择 Agent")
    llm_messages = _build_llm_messages(session, conversation, agent)
    if extra_content:
        llm_messages.append({"role": "user", "content": extra_content})
    estimated = _estimate_context_tokens(llm_messages, "") + model.max_output_tokens
    if estimated > model.context_length:
        raise ContextOverflowError(CONTEXT_OVERFLOW_DETAIL)



def regenerate(
    session: Session, conversation_id: int,
) -> StartReplyResponse:
    """重新生成最后一条 Agent 回复（原地重置，research R8）。"""
    conversation = _get_or_404(session, conversation_id)
    _assert_not_busy(session, conversation_id)
    last = _last_message(session, conversation_id)
    if last is None or last.role != "assistant":
        raise RegenerateInvalidError(MSG_REGENERATE_INVALID)
    agent, _model, _api_key = _resolve_generation_inputs(session, conversation)
    _assert_context_fits(session, conversation, agent)
    # 快照本次生成时刻的 Agent（切换后重新生成归属新 Agent）
    last.agent_id = agent.id
    last.agent_name = agent.name
    last.reasoning_content = None
    last.content = ""
    last.status = "generating"
    conversation.updated_at = _utcnow()
    session.commit()
    _start_generation_task(conversation_id, last.id, agent.id)
    return StartReplyResponse(
        user_message=None,
        reply_message_id=last.id,
        conversation=_to_summary(conversation),
    )



def switch_agent(
    session: Session, conversation_id: int, agent_id: int,
) -> ConversationSummary:
    """切换会话 Agent（只影响后续请求；生成中 409）。"""
    conversation = _get_or_404(session, conversation_id)
    _assert_not_busy(session, conversation_id)
    agent = session.get(AgentEntry, agent_id)
    if agent is None:
        raise AgentUnavailableError(MSG_AGENT_UNAVAILABLE)
    conversation.agent_id = agent_id
    session.commit()
    return _to_summary(conversation)


def get_generation_registry_status() -> int:
    """调试用：当前注册表任务数。"""
    return len(get_registry()._tasks)



async def stop_generation(conversation_id: int, message_id: int) -> None:
    """停止生成（FR-021，research R5）：取消任务 + 关上游流；终态走收尾逻辑。"""
    registry = get_registry()
    task = registry.get(message_id)
    if task is None or task.async_task is None:
        return  # 幂等：无任务即视为已停止
    if task.conversation_id != conversation_id:
        raise ConversationNotFoundError(f"会话 {conversation_id} 不存在")
    task.stopped = True
    task.cancel_event.set()  # 协作式取消：Runtime 在增量/工具/轮间检查（R8）
    task.async_task.cancel()



def mark_orphan_message(session: Session, conversation_id: int, message_id: int) -> MessageOut:
    """孤儿 generating 消息（订阅时任务已不存在）惰性标 incomplete 并返回最新状态。"""
    message = session.get(MessageEntry, message_id)
    if message is None:
        raise MessageNotFoundError(f"消息 {message_id} 不存在")
    if message.status == "generating":
        message.status = "incomplete"
        session.commit()
    return _to_message_out(message)



async def build_message_stream(
    session: Session,
    conversation_id: int,
    message_id: int,
) -> AsyncIterator[str]:
    """SSE 事件流（订阅者，research R1/R4）：重放→跟随→心跳。

    任务不存在时：completed → 立即 done；generating → 标 incomplete 后 done；
    incomplete → 立即 done（幂等订阅，FR-023）。
    """
    registry = get_registry()
    task = registry.get(message_id)
    if task is None:
        message = mark_orphan_message(session, conversation_id, message_id)
        done = StreamEvent(
            event=EVENT_DONE,
            data=json.dumps({
                "run_id": "", "seq": 0,
                "status": "cancelled",
                "reason": "生成任务已结束（服务重启或订阅晚到）",
                "usage_total": None,
                "message": message.model_dump(),
                "stopped": False,
            }, ensure_ascii=False),
        )
        yield _sse_frame(done)
        return
    queue = task.subscribe()
    ping_seconds = STREAM_PING_INTERVAL_SECONDS
    saw_terminal = False
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=ping_seconds)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            yield _sse_frame(event)
            if event.event == EVENT_DONE:
                saw_terminal = True
                return
    except GeneratorExit:
        # 客户端断开（关闭页面/连接中断）：由聊天接口触发取消（FR-027），
        # Runtime 自身不监听连接；SPA 内切换会话不断流（008 FR-022 不受影响）。
        if not saw_terminal and task.terminal_event is None:
            task.cancel_event.set()
        raise
    finally:
        task.unsubscribe(queue)
        if not saw_terminal and task.terminal_event is None:
            task.cancel_event.set()  # 兜底：订阅提前退出且无终态 → 协作取消


def _sse_frame(event: StreamEvent) -> str:
    """SSE 帧：event 名 + data JSON + 空行。"""
    return f"event: {event.event}\ndata: {event.data}\n\n"



def get_message(session: Session, conversation_id: int, message_id: int) -> MessageOut:
    """取单条消息（流订阅与停止的前置校验）。"""
    _get_or_404(session, conversation_id)
    message = session.get(MessageEntry, message_id)
    if message is None or message.conversation_id != conversation_id:
        raise MessageNotFoundError(f"消息 {message_id} 不存在")
    return _to_message_out(message)

"""统一 Agent Runtime（specs/009-agent-runtime）。

公共接口：RunRequest / RunLimits / RunHistoryMessage / execute_run。
契约主定义：specs/009-agent-runtime/contracts/agent-runtime-api.md §6
Runtime 不依赖 HTTP 对象与浏览器连接（FR-005）；聊天层与后续评测经本接口调用。
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from app.schemas.agent_runtime import EVENT_ERROR, EVENT_RUN_COMPLETED, RunCompletedData
from app.services.agent_runtime.events import RunEvent, RunEventEmitter
from app.services.agent_runtime.recorder import RunRecorder
from app.services.agent_runtime.runtime import AgentUnavailableError, RunContext, run_agent_loop


@dataclass
class RunLimits:
    """运行级能力限制：只能收窄 Agent 已有权限，不能额外授予（FR-003）。"""

    max_rounds: int | None = None
    allowed_tool_names: frozenset[str] | None = None
    disabled_skill_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass
class RunHistoryMessage:
    """调用方传入的有效历史（只含正文）。

    011 增补 seq：消息在 messages 表的顺序号；None = 运行内消息，
    不参与压缩边界推进（contracts/runtime-events-011.md §3）。
    """

    role: str  # "user" | "assistant"
    content: str
    seq: int | None = None


@dataclass
class RunRequest:
    """Runtime 运行入参（契约 §6 RunRequest）。

    011 增补：conversation_id / reply_message_id 供运行记录持久化与压缩
    边界读写定位；评测直调场景可两者皆空（跳过压缩逻辑）。
    """

    agent_id: int
    user_message: str
    history: list[RunHistoryMessage] = field(default_factory=list)
    limits: RunLimits = field(default_factory=RunLimits)
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    run_id: str = ""  # 空则自动生成 uuid4
    conversation_id: int | None = None  # 011 增补
    reply_message_id: int | None = None  # 011 增补

    def __post_init__(self) -> None:
        if not self.run_id:
            self.run_id = uuid.uuid4().hex


async def execute_run(request: RunRequest) -> AsyncIterator[RunEvent]:
    """执行一次 Agent 运行，产出契约 §2 事件流。

    最后一个事件必为 run_completed（恰一次）；任何退出路径都保证终态事件与
    MCP 资源清理（FR-029/035）。取消：request.cancel 置位或任务被 cancel。
    011：事件流同时喂给 RunRecorder 做运行记录持久化（FR-005）。
    """
    emitter = RunEventEmitter(request.run_id)
    ctx = RunContext(request=request, emitter=emitter)
    recorder = RunRecorder(
        request.run_id,
        conversation_id=request.conversation_id,
        reply_message_id=request.reply_message_id,
        agent_id=request.agent_id,
    )
    completed_yielded = False
    try:
        async for event in run_agent_loop(ctx):
            recorder.observe(event)
            if event.event == EVENT_RUN_COMPLETED:
                completed_yielded = True
            yield event
    except asyncio.CancelledError:
        # 硬取消：finally 清理（MCP 栈）后在同 task 内完成，CancelledError
        # 继续向外传播；终态由桥接层兜底（协议：终态恰一次）。
        recorder.finish(cancelled=True)
        raise
    except GeneratorExit:
        # 生成器被提前关闭：按取消收尾（运行记录不留永久 running，FR-007）
        recorder.finish(cancelled=True)
        raise
    except AgentUnavailableError as exc:
        from app.schemas.agent_runtime import ErrorEventData

        ctx.completed_data = RunCompletedData(
            status="error", reason=str(exc),
            content_text="".join(ctx.content_parts),
        )
        error_event = emitter.emit(
            EVENT_ERROR, ErrorEventData(category="unknown", message=str(exc)),
        )
        recorder.observe(error_event)
        yield error_event
    finally:
        await ctx.aclose()
    if not completed_yielded:
        # 异常路径兜底终态（正常路径由 run_agent_loop 产出，恰一次 FR-035）
        final = ctx.build_completed_event()
        recorder.observe(final)
        yield final
    recorder.close()  # 安全网：未收尾的路径按失败处理


__all__ = [
    "RunRequest",
    "RunLimits",
    "RunHistoryMessage",
    "RunEvent",
    "RunEventEmitter",
    "execute_run",
]

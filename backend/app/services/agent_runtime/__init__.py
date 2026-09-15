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
from app.services.agent_runtime.runtime import AgentUnavailableError, RunContext, run_agent_loop


@dataclass
class RunLimits:
    """运行级能力限制：只能收窄 Agent 已有权限，不能额外授予（FR-003）。"""

    max_rounds: int | None = None
    allowed_tool_names: frozenset[str] | None = None
    disabled_skill_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass
class RunHistoryMessage:
    """调用方传入的有效历史（只含正文）。"""

    role: str  # "user" | "assistant"
    content: str


@dataclass
class RunRequest:
    """Runtime 运行入参（契约 §6 RunRequest）。"""

    agent_id: int
    user_message: str
    history: list[RunHistoryMessage] = field(default_factory=list)
    limits: RunLimits = field(default_factory=RunLimits)
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    run_id: str = ""  # 空则自动生成 uuid4

    def __post_init__(self) -> None:
        if not self.run_id:
            self.run_id = uuid.uuid4().hex


async def execute_run(request: RunRequest) -> AsyncIterator[RunEvent]:
    """执行一次 Agent 运行，产出契约 §2 事件流。

    最后一个事件必为 run_completed（恰一次）；任何退出路径都保证终态事件与
    MCP 资源清理（FR-029/035）。取消：request.cancel 置位或任务被 cancel。
    """
    emitter = RunEventEmitter(request.run_id)
    ctx = RunContext(request=request, emitter=emitter)
    completed_yielded = False
    try:
        async for event in run_agent_loop(ctx):
            if event.event == EVENT_RUN_COMPLETED:
                completed_yielded = True
            yield event
    except asyncio.CancelledError:
        # 硬取消：finally 清理（MCP 栈）后在同 task 内完成，CancelledError
        # 继续向外传播；终态由桥接层兜底（协议：终态恰一次）。
        raise
    except AgentUnavailableError as exc:
        from app.schemas.agent_runtime import ErrorEventData

        ctx.completed_data = RunCompletedData(
            status="error", reason=str(exc),
            content_text="".join(ctx.content_parts),
        )
        yield emitter.emit(
            EVENT_ERROR, ErrorEventData(category="unknown", message=str(exc)),
        )
    finally:
        await ctx.aclose()
    if not completed_yielded:
        # 异常路径兜底终态（正常路径由 run_agent_loop 产出，恰一次 FR-035）
        yield ctx.build_completed_event()


__all__ = [
    "RunRequest",
    "RunLimits",
    "RunHistoryMessage",
    "RunEvent",
    "RunEventEmitter",
    "execute_run",
]

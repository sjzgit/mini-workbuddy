"""运行事件与序号调度（specs/009-agent-runtime/contracts/agent-runtime-api.md §1–§3）。

RunEventEmitter 保证 seq 运行内从 1 严格递增；事件 data 携带公共字段
run_id / seq，负载字段由契约 §3 的 Pydantic 模型（schemas/agent_runtime.py）验证。
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

# 事件类型常量（与 schemas/agent_runtime.py 保持同一来源）
from app.schemas.agent_runtime import (
    EVENT_ASK_USER,
    EVENT_COMPRESSION_COMPLETED,
    EVENT_COMPRESSION_FAILED,
    EVENT_COMPRESSION_FALLBACK,
    EVENT_COMPRESSION_STARTED,
    EVENT_CONTENT_DELTA,
    EVENT_ERROR,
    EVENT_MODEL_REQUEST_COMPLETED,
    EVENT_MODEL_REQUEST_STARTED,
    EVENT_PERMISSION_CHECKED,
    EVENT_REASONING_DELTA,
    EVENT_RUN_COMPLETED,
    EVENT_RUN_STARTED,
    EVENT_TOOL_CALL_COMPLETED,
    EVENT_TOOL_CALL_STARTED,
)

__all__ = [
    "EVENT_COMPRESSION_COMPLETED",
    "EVENT_COMPRESSION_FAILED",
    "EVENT_COMPRESSION_FALLBACK",
    "EVENT_COMPRESSION_STARTED",
    "EVENT_ASK_USER",
    "EVENT_PERMISSION_CHECKED",
    "RunEvent",
    "RunEventEmitter",
    "EVENT_RUN_STARTED",
    "EVENT_MODEL_REQUEST_STARTED",
    "EVENT_REASONING_DELTA",
    "EVENT_CONTENT_DELTA",
    "EVENT_MODEL_REQUEST_COMPLETED",
    "EVENT_TOOL_CALL_STARTED",
    "EVENT_TOOL_CALL_COMPLETED",
    "EVENT_ERROR",
    "EVENT_RUN_COMPLETED",
]


@dataclass
class RunEvent:
    """一条运行事件：SSE event 名 + 已含公共字段的 data dict。"""

    event: str
    seq: int
    run_id: str
    round: int | None
    call_id: str | None
    data: dict[str, Any]


class RunEventEmitter:
    """run_id 注入 + seq 分配 + 负载模型序列化。"""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._seq = 0

    def next_call_id(self, prefix: str) -> str:
        """调用标识（'m'/'t' 前缀 + 短随机，契约 §1）。"""
        import uuid as _uuid

        return f"{prefix}{_uuid.uuid4().hex[:8]}"

    def emit(
        self,
        event: str,
        payload: BaseModel,
        *,
        round: int | None = None,
        call_id: str | None = None,
    ) -> RunEvent:
        """产出一条事件：seq 自增，data = 公共字段 + 负载（契约 §3）。"""
        self._seq += 1
        data: dict[str, Any] = {
            "run_id": self.run_id,
            "seq": self._seq,
            **payload.model_dump(),
        }
        return RunEvent(
            event=event, seq=self._seq, run_id=self.run_id,
            round=round, call_id=call_id, data=data,
        )

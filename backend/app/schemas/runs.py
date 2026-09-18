"""运行记录 API 契约实现（specs/011，契约主定义 contracts/runs-api.md）。

字段与枚举 MUST 与契约逐条对齐，变更先改契约。
"""

from typing import Literal

from pydantic import BaseModel, Field

# ---- 枚举与常量（契约唯一主定义）----

RunStatusLiteral = Literal["running", "succeeded", "partial", "failed", "cancelled"]

PAGE_DEFAULT = 1
PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100


class RunSummary(BaseModel):
    """运行摘要（列表项；全部来自 runs 行快照，无关联查询）。"""

    run_id: str
    conversation_id: int | None
    agent_name: str
    model_name: str
    status: RunStatusLiteral
    # ---- 014 增补：运行启动时快照的会话工作空间（None = 未选择，data-model §1.2）----
    workspace_path: str | None = None
    end_reason: str = ""
    error_summary: str | None = None
    started_at: str
    finished_at: str | None = None
    total_duration_ms: int | None = None
    model_call_count: int = 0
    tool_call_count: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    first_output_ms: int | None = None


class RunListResponse(BaseModel):
    """GET /api/runs 响应。"""

    items: list[RunSummary]
    total: int
    page: int
    page_size: int


class RunEventOut(BaseModel):
    """详情时间线事件（安全负载，不含任何透传字段/正文全文/增量）。"""

    seq: int
    event_type: str
    round: int | None = None
    call_id: str | None = None
    data: dict
    created_at: str


class RunDetailResponse(BaseModel):
    """GET /api/runs/{run_id} 响应。"""

    summary: RunSummary
    events: list[RunEventOut]


class RunPayloadMeta(BaseModel):
    """载荷元数据（不含 content）。"""

    id: int
    call_id: str
    payload_type: str
    char_count: int


class RunPayloadContent(BaseModel):
    """GET 单条载荷响应（脱敏后完整内容）。"""

    id: int
    call_id: str
    payload_type: str
    char_count: int
    content: str

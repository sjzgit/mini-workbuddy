"""Agent Runtime 事件契约 Schema（API 契约实现）。

契约主定义：specs/009-agent-runtime/contracts/agent-runtime-api.md
字段与校验 MUST 与契约逐条对齐，变更先改契约。
"""

from typing import Any, Literal

from pydantic import BaseModel

# ---- 事件类型常量（契约 §2 的代码落点，前后端统一消费）----

EVENT_RUN_STARTED = "run_started"
EVENT_MODEL_REQUEST_STARTED = "model_request_started"
EVENT_REASONING_DELTA = "reasoning_delta"
EVENT_CONTENT_DELTA = "content_delta"
EVENT_MODEL_REQUEST_COMPLETED = "model_request_completed"
EVENT_TOOL_CALL_STARTED = "tool_call_started"
EVENT_TOOL_CALL_COMPLETED = "tool_call_completed"
EVENT_ERROR = "error"
EVENT_RUN_COMPLETED = "run_completed"

# ---- 复合字面量 ----

ModelRequestStatusLiteral = Literal["ok", "error", "cancelled"]
ToolTypeLiteral = Literal["builtin", "mcp", "skill"]
ToolCallStatusLiteral = Literal["success", "error", "denied", "cancelled"]
RunStatusLiteral = Literal["completed", "max_rounds", "error", "cancelled"]


class UsageInfo(BaseModel):
    """模型接口实际返回的 Token 用量；None = 未返回（未知），禁止填 0（FR-034）。"""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    def merge_add(self, other: "UsageInfo | None") -> "UsageInfo":
        """求和合并：任一操作数该项未知则结果该项未知。"""
        if other is None:
            return self.model_copy()
        merged = UsageInfo()
        for field_name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            mine = getattr(self, field_name)
            theirs = getattr(other, field_name)
            setattr(
                merged, field_name,
                None if mine is None or theirs is None else mine + theirs,
            )
        return merged


class RunStartedData(BaseModel):
    """event: run_started。"""

    agent_id: int
    agent_name: str


class ModelRequestStartedData(BaseModel):
    """event: model_request_started。"""

    round: int
    call_id: str


class DeltaData(BaseModel):
    """event: reasoning_delta / content_delta 共用负载。"""

    round: int
    call_id: str
    text: str


class ModelRequestCompletedData(BaseModel):
    """event: model_request_completed：与 model_request_started 按 call_id 配对。"""

    round: int
    call_id: str
    status: ModelRequestStatusLiteral
    duration_ms: int
    usage: UsageInfo | None = None


class ToolCallStartedData(BaseModel):
    """event: tool_call_started（010 增补 params/display_name/server_name 供过程卡片展示，
    契约见 specs/010-tool-execution-display/contracts/display-events.md §1）。"""

    round: int
    call_id: str
    tool_name: str
    tool_type: ToolTypeLiteral
    params_summary: str
    # ---- 010 增补（展示用，日志仍只用 params_summary）----
    params: str = ""  # 完整参数文本，超 runtime_tool_params_max_chars 截断 + 截断标记
    display_name: str = ""  # 易读名：builtin=注册表 display_name；mcp=原工具名；skill="加载 Skill"
    server_name: str | None = None  # MCP Server 显示名，仅 tool_type=mcp 非空


class ToolCallCompletedData(BaseModel):
    """event: tool_call_completed：与 tool_call_started 按 call_id 配对。"""

    round: int
    call_id: str
    tool_name: str
    tool_type: ToolTypeLiteral
    status: ToolCallStatusLiteral
    duration_ms: int
    result_summary: str
    # ---- 010 增补（展示用，日志仍只用 result_summary）----
    result: str = ""  # 完整结果文本：成功=result_for_model；失败=人话原因（无堆栈）；超限截断 + 标记
    display_name: str = ""
    server_name: str | None = None


class ErrorEventData(BaseModel):
    """event: error（沿用 008 类别枚举，文案直接可展示）。"""

    category: str  # StreamErrorCategoryLiteral（008 契约）；字符串避免跨模块 Literal 漂移
    message: str


class RunCompletedData(BaseModel):
    """event: run_completed：运行终态，每次运行恰一次且必为最后一个事件。

    content_text/reasoning_text 仅供桥接层落库（SSE 转发时剥离，契约 §3 约束）。
    """

    status: RunStatusLiteral
    reason: str
    usage_total: UsageInfo | None = None
    content_text: str = ""
    reasoning_text: str | None = None
    message: dict[str, Any] | None = None  # MessageOut(008) 形态；桥接层回填，占位行被删时 None
    stopped: bool = False

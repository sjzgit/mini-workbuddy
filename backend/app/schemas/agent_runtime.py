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
# ---- 011 增补：上下文压缩事件（contracts/runtime-events-011.md §1）----
EVENT_COMPRESSION_STARTED = "compression_started"
EVENT_COMPRESSION_COMPLETED = "compression_completed"
EVENT_COMPRESSION_FAILED = "compression_failed"
EVENT_COMPRESSION_FALLBACK = "compression_fallback"
# ---- 013 增补：Ask User 询问事件（specs/013-ask-user-tool/contracts/ask-user-api.md §2）----
EVENT_ASK_USER = "ask_user"

# ---- 014 增补：权限判定事件（specs/014-workspace-permission/contracts/workspace-permission-api.md §2.1）----
EVENT_PERMISSION_CHECKED = "permission_checked"

# ---- 复合字面量 ----

ModelRequestStatusLiteral = Literal["ok", "error", "cancelled"]
ToolTypeLiteral = Literal["builtin", "mcp", "skill"]
ToolCallStatusLiteral = Literal["success", "error", "denied", "cancelled"]
RunStatusLiteral = Literal["completed", "max_rounds", "error", "cancelled"]
# ---- 011 增补 ----
ModelRequestPurposeLiteral = Literal["chat", "context_compression"]
CompressionTriggerLiteral = Literal["threshold", "precheck"]
CompressionFailureLiteral = Literal[
    "timeout", "model_error", "empty_summary", "save_failed", "cancelled",
]


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
    # ---- 011 增补：模型名称快照（runs 表快照字段来源）----
    model_name: str = ""
    model_identifier: str = ""
    # ---- 014 增补：会话工作空间快照（runs.workspace_path 快照来源，data-model §5.2）----
    workspace_path: str | None = None


class ModelRequestStartedData(BaseModel):
    """event: model_request_started。"""

    round: int
    call_id: str
    # ---- 011 增补：请求用途（压缩请求计入模型调用统计并标记用途，FR-045）----
    purpose: ModelRequestPurposeLiteral = "chat"


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
    # ---- 011 增补 ----
    purpose: ModelRequestPurposeLiteral = "chat"
    # Recorder 透传字段（SSE 转发时剥离，契约 runtime-events-011.md §2.2）：
    request_messages: list[dict[str, Any]] | None = None  # 该次请求完整 messages
    output_content: str | None = None  # 该次响应正文全文
    output_reasoning: str | None = None  # 该次响应思考全文
    output_tool_calls: list[dict[str, str]] | None = None  # 该次响应的工具调用（name+arguments）


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
    # ---- 011 增补（Recorder 透传，SSE 剥离；完整保存进 run_payloads，不截断）----
    params_full: str = ""


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
    # ---- 011 增补（Recorder 透传，SSE 剥离；完整保存进 run_payloads，不截断）----
    result_full: str = ""


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


# ---- 011 增补：上下文压缩事件负载（contracts/runtime-events-011.md §1）----


class CompressionStartedData(BaseModel):
    """event: compression_started：一轮压缩尝试开始。"""

    trigger_reason: CompressionTriggerLiteral
    estimated_input_tokens: int  # 估算口径（FR-024，非实际用量）
    available_input_tokens: int
    trigger_ratio: float
    # ---- 011 Recorder 透传（SSE 转发时剥离）----
    input_full: str = ""  # 摘要请求完整输入文本（提示词+待压缩内容）


class CompressionCompletedData(BaseModel):
    """event: compression_completed：摘要生成并写回成功。"""

    estimated_tokens_before: int
    estimated_tokens_after: int
    messages_compressed: int
    groups_compressed: int
    kept_rounds: int
    summary_estimated_tokens: int
    batches: int
    duration_ms: int
    boundary_seq: int
    # ---- 011 Recorder 透传（SSE 转发时剥离）----
    output_full: str = ""  # 最终摘要全文


class CompressionFailedData(BaseModel):
    """event: compression_failed：摘要请求超时/模型错误/空摘要/写回失败/取消。"""

    reason: CompressionFailureLiteral
    estimated_tokens_before: int
    duration_ms: int


class CompressionFallbackData(BaseModel):
    """event: compression_fallback：转入备用裁剪（只影响本次请求，边界不变）。"""

    reason: str
    dropped_groups: int
    kept_groups: int
    estimated_tokens_after: int


# ---- 013 增补：Ask User 事件负载（contracts/ask-user-api.md §2）----


class AskUserData(BaseModel):
    """event: ask_user：模型向用户发起询问，等待回答期间运行暂停推进。"""

    round: int
    call_id: str  # 工具调用标识；回答端点按此定位挂起的等待
    question: str
    options: list[str] = []  # 空 = 开放式（输入框）
    multi_select: bool = False  # 仅选项式有意义；缺省单选


# ---- 014 增补：权限判定事件负载（contracts/workspace-permission-api.md §2.1）----


class PermissionCheckedData(BaseModel):
    """event: permission_checked：file_read_write / shell 每次权限判定一条（含 allow，审计）。"""

    round: int
    call_id: str
    decision: Literal["allow", "ask_user", "deny"]  # 三值决策（Invariant 4，禁止布尔）
    tool_name: str
    path: str  # 规范化后的目标路径（不含文件内容，FR-033）
    reason: str  # 人话原因

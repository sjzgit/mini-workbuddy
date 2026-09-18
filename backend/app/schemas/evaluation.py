"""评测 API 契约实现（specs/012，契约主定义 contracts/evaluation-api.md）。

字段与枚举 MUST 与契约逐条对齐，变更先改契约。
枚举唯一主定义：contracts/evaluation-api.md §enums（本文件只做消费级定义）。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ---- 枚举与常量（契约唯一主定义）----

EvaluatorTypeLiteral = Literal["llm_judge", "exact_match"]
EVALUATOR_TYPES: tuple[str, ...] = ("llm_judge", "exact_match")

TaskStatusLiteral = Literal["pending"]

RunStatusLiteral = Literal[
    "pending", "running", "paused", "completed", "cancelled", "failed", "interrupted",
]
RUN_STATUSES: tuple[str, ...] = (
    "pending", "running", "paused", "completed", "cancelled", "failed", "interrupted",
)

CaseRunStatusLiteral = Literal[
    "pending", "running", "passed", "failed", "execution_failed", "judge_failed", "cancelled",
]
CASE_RUN_STATUSES: tuple[str, ...] = (
    "pending", "running", "passed", "failed", "execution_failed", "judge_failed", "cancelled",
)

CaseErrorTypeLiteral = Literal[
    "agent_unavailable", "model_error", "timeout", "cancelled",
    "interrupted", "judge_invalid_output", "judge_model_error", "internal",
]

# 运行状态机合法跳转（data-model.md §4.2，实现侧唯一消费入口）
RUN_STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "pending": ("running", "cancelled"),
    "running": ("paused", "completed", "cancelled", "failed", "interrupted"),
    "paused": ("running", "cancelled", "interrupted"),
    "completed": (),
    "cancelled": (),
    "failed": (),
    "interrupted": ("running",),
}

# CaseRun 可重试状态（契约 §5 retry）
RETRYABLE_CASE_RUN_STATUSES: frozenset[str] = frozenset(
    {"execution_failed", "judge_failed", "failed", "cancelled"},
)

# 评分器默认配置
DEFAULT_PASS_THRESHOLD = 80
JUDGE_DEFAULT_TEMPERATURE = "0.0"
JUDGE_DEFAULT_MAX_TOKENS = 1024

# 分页（契约 §5 GET /runs）
RUN_PAGE_DEFAULT = 1
RUN_PAGE_SIZE_DEFAULT = 20
RUN_PAGE_SIZE_MAX = 100


# ---- 数据集与用例 ----


class DatasetSaveRequest(BaseModel):
    """创建/更新数据集请求。"""

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("数据集名称不能为空白")
        return value.strip()


class DatasetOut(BaseModel):
    """数据集输出（列表项与详情同构）。"""

    id: int
    name: str
    description: str
    case_count: int = 0
    created_at: str
    updated_at: str


class CaseSaveRequest(BaseModel):
    """创建/更新用例请求（expected_answer/scoring_criteria 可空）。"""

    user_question: str
    expected_answer: str | None = None
    scoring_criteria: str | None = None

    @field_validator("user_question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("用户问题不能为空白")
        return value.strip()


class CaseOut(BaseModel):
    """用例输出。"""

    id: int
    dataset_id: int
    user_question: str
    expected_answer: str | None
    scoring_criteria: str | None
    created_at: str
    updated_at: str


class ImportResult(BaseModel):
    """导入结果（整体拒绝时 errors 携带定位信息，HTTP 422）。"""

    imported_cases: int
    skipped_cases: int = 0
    errors: list[str] = []


# ---- 评测任务 ----


class EvaluatorConfig(BaseModel):
    """评分器配置（契约 §4；exact_match 仅接受空配置）。"""

    model_config = {"extra": "allow"}

    model_model_id: int | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    prompt_template: str | None = None


class TaskSaveRequest(BaseModel):
    """创建评测任务请求（契约 §4）。"""

    name: str = Field(min_length=1, max_length=100)
    agent_id: int
    dataset_id: int
    evaluator_type: EvaluatorTypeLiteral
    evaluator_config: dict[str, Any] = Field(default_factory=dict)
    pass_threshold: int = Field(default=DEFAULT_PASS_THRESHOLD, ge=0, le=100)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("任务名称不能为空白")
        return value.strip()


class TaskSummary(BaseModel):
    """任务列表项（不含三快照大字段）。"""

    id: int
    name: str
    agent_id: int
    agent_name: str
    dataset_id: int
    dataset_name: str
    evaluator_type: str
    evaluator_config: dict[str, Any]
    pass_threshold: int
    status: str
    case_count: int
    last_run_id: int | None = None
    last_run_status: str | None = None
    created_at: str
    updated_at: str


class TaskOut(TaskSummary):
    """任务详情（含三快照）。"""

    agent_snapshot: dict[str, Any]
    dataset_snapshot: dict[str, Any]
    evaluator_snapshot: dict[str, Any]


# ---- 评测运行 ----


class EvaluationRunOut(BaseModel):
    """评测运行输出（契约 §5 EvaluationRunOut）。"""

    id: int
    task_id: int
    run_id: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    interrupted_at: str | None = None
    interrupted_reason: str | None = None
    total_cases: int = 0
    completed_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    execution_failed_cases: int = 0
    judge_failed_cases: int = 0
    cancelled_cases: int = 0
    average_score: int | None = None
    pass_rate: int | None = None
    total_duration_ms: int | None = None
    total_tokens: int | None = None
    created_at: str


class RunListResponse(BaseModel):
    """GET /api/evaluation/runs 响应。"""

    items: list[EvaluationRunOut]
    total: int
    page: int
    page_size: int


class SnapshotCaseOut(BaseModel):
    """快照 Case 内容（从任务 dataset_snapshot 提取）。"""

    case_id: int
    user_question: str
    expected_answer: str | None = None
    scoring_criteria: str | None = None


class CaseRunOut(BaseModel):
    """用例运行输出（契约 §5 CaseRunOut）。"""

    id: int
    evaluation_run_id: int
    dataset_case_id: int
    status: str
    agent_run_id: str | None = None
    score: int | None = None
    reason: str | None = None
    evaluator_type: str | None = None
    evaluator_metadata: dict[str, Any] | None = None
    duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    tool_call_count: int | None = None
    model_call_count: int | None = None
    iteration_count: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    attempt: int = 1
    started_at: str | None = None
    finished_at: str | None = None
    case_index: int | None = None
    snapshot_case: SnapshotCaseOut | None = None


class RetryRequest(BaseModel):
    """失败 Case 重试请求（契约 §5 retry）。"""

    case_run_id: int


class RetryResponse(BaseModel):
    """重试响应。"""

    run: EvaluationRunOut
    case_run: CaseRunOut


class OkResponse(BaseModel):
    """删除/控制类操作的统一确认。"""

    ok: bool = True

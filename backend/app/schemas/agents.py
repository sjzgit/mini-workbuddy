"""Agent 管理 Pydantic Schema（API 契约实现）。

契约主定义：specs/007-agent-management/contracts/agents-api.md
字段与校验 MUST 与契约逐条对齐，变更先改契约。
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ---- 常量（契约"枚举与常量"节的主定义落点）----

ResourceTypeLiteral = Literal["tool", "skill", "mcp"]

ThinkingLevelLiteral = Literal["off", "low", "medium", "high"]

ENABLE_DEEP_THINKING_DEFAULT = False
THINKING_LEVEL_DEFAULT = "off"

MAX_ROUNDS_DEFAULT = 10
MAX_ROUNDS_MIN = 1
MAX_ROUNDS_MAX = 100


class BindingRef(BaseModel):
    """提交体中的绑定引用。"""

    resource_type: ResourceTypeLiteral
    resource_id: int


class BindingItem(BaseModel):
    """绑定项（详情返回）：enabled 实时计算，无快照（research R6）。"""

    resource_type: ResourceTypeLiteral
    resource_id: int
    name: str
    description: str
    enabled: bool


class BindingOption(BaseModel):
    """候选项（binding-options 返回）：只含启用资源。"""

    id: int
    name: str
    description: str
    selected: bool = False


class ModelOption(BaseModel):
    """模型候选项：展示名称与模型标识（FR-013），不显示内部编号之外的信息冗余。"""

    id: int
    display_name: str
    model_identifier: str
    is_default: bool


class PromptVersionItem(BaseModel):
    """提示词版本项。"""

    version: int
    content: str
    created_at: str


class AgentSaveRequest(BaseModel):
    """新建/编辑提交体（契约 AgentSaveRequest）。

    校验失败 → FastAPI 422：name 空/超长、max_rounds 越界、bindings 元素
    枚举非法、同一资源重复绑定（model_validator 判定）。
    """

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    model_id: int
    system_prompt: str = ""
    max_rounds: int = Field(default=MAX_ROUNDS_DEFAULT, ge=MAX_ROUNDS_MIN, le=MAX_ROUNDS_MAX)
    enable_deep_thinking: bool = ENABLE_DEEP_THINKING_DEFAULT
    thinking_level: ThinkingLevelLiteral = THINKING_LEVEL_DEFAULT
    is_default: bool = False
    bindings: list[BindingRef] | None = None

    @model_validator(mode="after")
    def _normalize(self) -> "AgentSaveRequest":
        if not self.name.strip():
            raise ValueError("Agent 名称不能为空")
        self.name = self.name.strip()
        seen: set[tuple[str, int]] = set()
        for binding in self.bindings or []:
            key = (binding.resource_type, binding.resource_id)
            if key in seen:
                raise ValueError(f"重复绑定：{binding.resource_type} #{binding.resource_id}")
            seen.add(key)
        return self


class AgentOption(BaseModel):
    """删除默认 Agent 时供选择的候选（同时用于引用保护响应）。"""

    id: int
    name: str


class DeleteResponse(BaseModel):
    """DELETE 响应：cleared_default=true 表示默认状态已随最后一个 Agent 清除。"""

    deleted: bool = True
    cleared_default: bool = False


class RequiresNewDefaultBody(BaseModel):
    """删除默认 Agent 缺 new_default_id 的 409 响应体。"""

    detail: str = "该 Agent 是默认 Agent，请先选择新的默认 Agent"
    requires_new_default: bool = True
    candidates: list[AgentOption]


class ReferencedByAgentBody(BaseModel):
    """资源被 Agent 引用时的 409 响应体。"""

    detail: str
    referenced_by_agents: list[AgentOption]


class AgentListItem(BaseModel):
    """列表卡片项（契约 AgentListItem）：bindings 为全量（FR-004 演进：按类分行全量展示）。"""

    id: int
    name: str
    description: str
    model_display_name: str
    model_identifier: str
    tool_count: int
    skill_count: int
    mcp_count: int
    bindings: list[BindingItem]
    is_default: bool
    updated_at: str


class AgentDetail(BaseModel):
    """详情/保存返回（契约 AgentDetail）。"""

    id: int
    name: str
    description: str
    model_id: int
    model_display_name: str
    model_identifier: str
    system_prompt: str
    prompt_versions: list[PromptVersionItem]
    bindings: list[BindingItem]
    max_rounds: int
    enable_deep_thinking: bool
    thinking_level: ThinkingLevelLiteral
    is_default: bool
    updated_at: str


class BindingOptionsResponse(BaseModel):
    """资源候选项聚合响应（一次拉取四类候选 + 提示词模板）。"""

    tools: list[BindingOption]
    skills: list[BindingOption]
    mcp_servers: list[BindingOption]
    models: list[ModelOption]
    prompt_template: str

"""Skills 管理契约实现。

契约主定义：specs/004-skills-mcp-management/contracts/skills-api.md
            specs/005-skill-file-editor/contracts/skill-files-api.md（目录树与文件编辑）
本文件字段与类型 MUST 与契约逐字段对齐；变更先改契约再同步此处与前端 api/skills.ts。
"""

from typing import Literal

from pydantic import BaseModel, Field


class SkillItem(BaseModel):
    """列表项（GET /api/skills，契约 §3）。"""

    dir_name: str
    name: str
    description: str
    enabled: bool
    updated_at: str  # ISO 8601（skill.md mtime，文件不可得时为 DB updated_at）


class SkillDetail(SkillItem):
    """详情（GET /api/skills/{dir_name}），编辑页数据源。"""

    instruction: str


class SkillUpdateRequest(BaseModel):
    """PUT /api/skills/{dir_name} 提交体（契约 §3）。"""

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    instruction: str = Field(default="", max_length=200000)


class SkillToggleRequest(BaseModel):
    """PUT /api/skills/{dir_name}/enabled 提交体。"""

    enabled: bool


class SkillRefreshResult(BaseModel):
    """POST /api/skills/refresh 响应（契约 §3）。"""

    items: list[SkillItem]
    skipped: list[str]


class SkillDeletedResponse(BaseModel):
    """DELETE /api/skills/{dir_name} 响应。"""

    deleted: bool = True


# ---- 目录树与文件在线编辑（005，契约 skill-files-api.md §2）----

FileNodeType = Literal["file", "dir"]
NotEditableReason = Literal["not_text", "too_large"]


class SkillFileNode(BaseModel):
    """目录树节点（递归；文件 children 恒为 []）。"""

    name: str
    path: str
    type: FileNodeType
    children: list["SkillFileNode"] = []


class SkillFileContent(BaseModel):
    """单文件读取响应；editable=false 时 content 恒为 null（零乱码）。"""

    path: str
    editable: bool
    reason: NotEditableReason | None = None
    content: str | None = None
    size: int


class SkillFileWriteRequest(BaseModel):
    """PUT /api/skills/{dir_name}/file 提交体（覆盖写，空内容合法）。"""

    path: str = Field(min_length=1, max_length=500)
    content: str = Field(default="", max_length=2_000_000)


class SkillFileSavedResponse(BaseModel):
    """PUT /api/skills/{dir_name}/file 成功响应。"""

    saved: bool = True
    path: str

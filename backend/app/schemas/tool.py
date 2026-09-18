"""工具管理契约实现。

契约主定义：specs/003-tool-management/contracts/api-contract.md（HTTP 结构）
            specs/003-tool-management/contracts/tool-definitions.md（执行结果/错误码）
本文件字段与类型 MUST 与契约一致；错误码与危险类别是唯一主定义的实现载体。
"""

from typing import Any, Literal

from pydantic import BaseModel

# ---- 错误码枚举（tool-definitions.md §5，实现侧只消费）----

# 入口层（执行前三查 + 兜底，FR-010/012）
# 工具层（各工具实现抛出）：unknown_timezone / dangerous_command_blocked /
#   command_timeout / path_outside_root / file_not_found / file_too_large / file_not_text
# 014 权限层增补（specs/014-workspace-permission/contracts/workspace-permission-api.md §3）：
#   system_protected_path / permission_denied_by_user / path_resolution_failed /
#   permission_check_failed / ask_user_unavailable
ToolErrorCode = Literal[
    "tool_not_found",
    "tool_disabled",
    "invalid_params",
    "execution_error",
    "unknown_timezone",
    "dangerous_command_blocked",
    "command_timeout",
    "path_outside_root",
    "file_not_found",
    "file_too_large",
    "file_not_text",
    "system_protected_path",
    "permission_denied_by_user",
    "path_resolution_failed",
    "permission_check_failed",
    "ask_user_unavailable",
]

# 危险命令类别（tool-definitions.md §5）
DangerCategory = Literal[
    "recursive_delete_system",
    "format_disk",
    "modify_system_permissions",
    "disable_security",
    "secret_exfiltration",
    "remote_script_execution",
]


class ToolParam(BaseModel):
    """工具参数定义（详情页参数表的一行）。"""

    name: str
    type: Literal["string", "enum"]
    required: bool
    description: str


class ToolItem(BaseModel):
    """列表项（GET /api/tools）。"""

    name: str
    display_name: str
    purpose: str
    params_summary: str
    enabled: bool
    is_builtin: bool
    updated_at: str  # ISO 8601


class ToolDetail(ToolItem):
    """详情（GET /api/tools/{name}），补全参数表与三节说明。"""

    params: list[ToolParam]
    usage_scenarios: str
    input_requirements: str
    restrictions: str


class ToolToggleRequest(BaseModel):
    """PUT /api/tools/{name}/enabled 提交体。"""

    enabled: bool


class ToolExecutionResult(BaseModel):
    """统一执行入口的唯一返回结构（tool-definitions.md §4）。

    HTTP 与未来 Agent Loop 共用；"执行失败"是业务结果而非 HTTP 错误。
    """

    success: bool
    error_code: ToolErrorCode | None = None
    message: str
    output: str | None = None
    extra: dict[str, Any] | None = None

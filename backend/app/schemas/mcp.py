"""MCP 管理契约实现。

契约主定义：specs/004-skills-mcp-management/contracts/mcp-api.md
本文件字段与类型 MUST 与契约逐字段对齐；变更先改契约再同步此处与前端 api/mcp.ts。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

ServerType = Literal["stdio", "http"]
TestStatus = Literal["success", "failed", "config_changed"]
TestCategory = Literal[
    "command_not_found",
    "process_failed",
    "timeout",
    "protocol_incompatible",
    "server_error",
    "connection_failed",
    "unknown",
]

# 三态协议值：字符串 = 替换/新增；None = 保留原值（契约 §2）
SecretOverrides = dict[str, str | None]

_MASK = "••••••"  # 只读展示掩码（契约 §2/§6）


def mask_value() -> str:
    """掩码占位（函数形态便于测试与前端口径对齐）。"""
    return _MASK


class McpToolParam(BaseModel):
    """工具参数说明（inputSchema 解析结果，契约 §2）。"""

    name: str
    type: str
    required: bool
    description: str


class McpToolInfo(BaseModel):
    """测试发现的单个工具（tools_json 快照元素，契约 §2）。"""

    name: str
    description: str = ""
    params: list[McpToolParam] = []


class McpServerItem(BaseModel):
    """列表项（GET /api/mcp/servers，契约 §2）。"""

    id: int
    name: str
    description: str
    server_type: ServerType
    enabled: bool
    last_test_status: TestStatus | None = None
    last_test_message: str | None = None
    last_test_tool_count: int | None = None
    last_test_at: str | None = None
    updated_at: str


class McpServerDetail(McpServerItem):
    """详情（GET /api/mcp/servers/{id}），编辑页与工具弹窗数据源。

    MUST NOT 出现：env/headers 明文、secret_ref 指针、任何密文（契约 §2）。
    """

    command: str | None = None
    command_args: list[str] | None = None
    env_masked: dict[str, str] | None = None
    url: str | None = None
    headers_masked: dict[str, str] | None = None
    tools: list[McpToolInfo] = []


class McpServerUpsertRequest(BaseModel):
    """POST/PUT 提交体（契约 §2，含 stdio/http 字段互斥与三态协议）。"""

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    server_type: ServerType
    command: str | None = Field(default=None, max_length=500)
    command_args: list[str] | None = None
    env: SecretOverrides | None = None
    url: str | None = None
    headers: SecretOverrides | None = None

    @model_validator(mode="after")
    def _check_type_fields(self) -> "McpServerUpsertRequest":
        if self.server_type == "stdio":
            if not (self.command and self.command.strip()):
                raise ValueError("本机启动型 Server 必须填写启动命令")
            if self.url is not None or self.headers is not None:
                raise ValueError("本机启动型 Server 不能填写 url 或请求 Header")
        else:  # http
            if not self.url:
                raise ValueError("远程 HTTP 型 Server 必须填写 url")
            try:
                parsed = HttpUrl(self.url)
            except Exception as exc:
                raise ValueError(f"url 格式不合法：{self.url}") from exc
            if parsed.scheme not in ("http", "https"):
                raise ValueError("url 仅支持 http/https")
            if self.command is not None or self.command_args is not None or self.env is not None:
                raise ValueError("远程 HTTP 型 Server 不能填写启动命令、参数或环境变量")
        if self.command_args and len(self.command_args) > 64:
            raise ValueError("启动参数最多 64 项")
        if any(len(arg) > 500 for arg in (self.command_args or [])):
            raise ValueError("启动参数单项最长 500 字符")
        for overrides in (self.env, self.headers):
            if not overrides:
                continue
            for key in overrides:
                if not key or len(key) > 100:
                    raise ValueError(f"键名非法或超长：{key!r}（1–100 字符）")
        return self


class McpToggleRequest(BaseModel):
    """PUT /api/mcp/servers/{id}/enabled 提交体。"""

    enabled: bool


class McpTestResult(BaseModel):
    """POST /api/mcp/servers/{id}/test 响应（契约 §2）。"""

    status: Literal["success", "failed"]
    category: TestCategory | None = None
    message: str
    tool_count: int | None = None
    tools: list[McpToolInfo] = []
    item: McpServerItem


class McpDeletedResponse(BaseModel):
    """DELETE /api/mcp/servers/{id} 响应。"""

    deleted: bool = True


def parse_input_schema(schema: dict[str, Any] | None) -> list[McpToolParam]:
    """工具 inputSchema（JSON Schema object）→ 参数表（契约 §2）。

    无 schema / 非 object / 无 properties 时返回 []。
    """
    if not isinstance(schema, dict) or schema.get("type") not in (None, "object"):
        return []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    required = schema.get("required")
    required_names = set(required) if isinstance(required, list) else set()
    params: list[McpToolParam] = []
    for param_name, spec in properties.items():
        param_type = "any"
        description = ""
        if isinstance(spec, dict):
            raw_type = spec.get("type")
            if isinstance(raw_type, str) and raw_type:
                param_type = raw_type
            raw_desc = spec.get("description")
            if isinstance(raw_desc, str):
                description = raw_desc
        params.append(
            McpToolParam(
                name=str(param_name),
                type=param_type,
                required=param_name in required_names,
                description=description,
            )
        )
    return params

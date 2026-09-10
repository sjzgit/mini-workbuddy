"""内置工具元数据注册表。

契约主定义：specs/003-tool-management/contracts/tool-definitions.md §1–§3
说明文本逐字对齐契约；参数校验模型是"输入是否正确"检查（FR-010 ③）的载体。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.tool import ToolParam

CURRENT_TIME = "current_time"
SHELL = "shell"
FILE_READ_WRITE = "file_read_write"

# ---- 参数校验模型（契约 §2；多余参数一律拒绝，属"输入是否正确"检查）----


class CurrentTimeParams(BaseModel):
    """current_time 参数。"""

    model_config = ConfigDict(extra="forbid")

    timezone: str | None = Field(
        default=None,
        description="IANA 时区名称，如 Asia/Shanghai、America/New_York、Etc/UTC；"
        "避免使用 CST 等含义不明确的缩写。省略时使用系统默认时区",
    )


class ShellParams(BaseModel):
    """shell 参数。"""

    model_config = ConfigDict(extra="forbid")

    command: str = Field(
        min_length=1,
        max_length=10000,
        description="要执行的命令（≤ 10000 字符）",
    )


FileAction = Literal["read", "write"]


class FileReadWriteParams(BaseModel):
    """file_read_write 参数（action + path 必填；content 仅 write 必填）。"""

    model_config = ConfigDict(extra="forbid")

    action: FileAction
    path: str = Field(min_length=1)
    content: str | None = None

    @model_validator(mode="after")
    def validate_content_for_write(self) -> "FileReadWriteParams":
        """write 时 content 必填（允许空串 = 创建空文件）；read 时忽略。"""
        if self.action == "write" and self.content is None:
            raise ValueError("write 操作必须提供 content（可为空字符串）")
        return self


# ---- 元数据（契约 §1/§3，说明文本逐字对齐）----


class ToolDefinition(BaseModel):
    """一个内置工具的完整注册信息。"""

    name: str
    display_name: str
    purpose: str
    params: list[ToolParam]
    params_summary: str
    usage_scenarios: str
    input_requirements: str
    restrictions: str
    is_builtin: bool = True
    params_model: type[BaseModel]


_REGISTRY: dict[str, ToolDefinition] = {
    CURRENT_TIME: ToolDefinition(
        name=CURRENT_TIME,
        display_name="当前时间",
        purpose="查询指定时区的当前日期和时间",
        params=[
            ToolParam(
                name="timezone",
                type="string",
                required=False,
                description=(
                    "IANA 时区名称，如 Asia/Shanghai、America/New_York、Etc/UTC。"
                    "避免使用 CST 等含义不明确的缩写（IANA 名称严格校验，缩写无法识别）。"
                    "省略时使用系统默认时区"
                ),
            ),
        ],
        params_summary="timezone（可选）",
        usage_scenarios="需要知道当前日期、时间或某地本地时间时使用，例如日程判断、时间计算、日志确认。",
        input_requirements="时区必须是 IANA 时区名称；未提供时返回系统默认时区的时间。",
        restrictions="不适用 CST、GMT+8 等缩写或偏移写法；无法识别的时区将返回错误。",
        params_model=CurrentTimeParams,
    ),
    SHELL: ToolDefinition(
        name=SHELL,
        display_name="Shell 命令",
        purpose="执行系统命令并返回输出与执行状态",
        params=[
            ToolParam(
                name="command",
                type="string",
                required=True,
                description=(
                    "要执行的命令（≤ 10000 字符）。用于查看系统信息、搜索文件、运行脚本、"
                    "执行测试等。危险命令（递归删除系统目录、格式化磁盘、修改关键系统权限、"
                    "关闭安全防护、读取并外传密钥、直接执行远程下载的脚本）会在执行前被拦截"
                ),
            ),
        ],
        params_summary="command（必填）",
        usage_scenarios="查看系统信息、搜索文件、运行脚本、执行测试等本地命令行操作。",
        input_requirements=(
            "一条完整的命令字符串；执行超时上限 60 秒，输出超过 20000 字符将被截断并标注。"
        ),
        restrictions=(
            "以下六类危险命令会在执行前被拦截并拒绝：递归删除根目录或系统目录、格式化磁盘、"
            "修改关键系统权限、关闭安全防护、读取并外传密钥、未经检查直接执行远程下载的脚本。"
        ),
        params_model=ShellParams,
    ),
    FILE_READ_WRITE: ToolDefinition(
        name=FILE_READ_WRITE,
        display_name="文件读写",
        purpose="在授权目录内读取、创建和修改文本文件",
        params=[
            ToolParam(
                name="action",
                type="enum",
                required=True,
                description="read 读取文件内容；write 创建或覆盖写入文件",
            ),
            ToolParam(
                name="path",
                type="string",
                required=True,
                description=(
                    "相对授权目录的文件路径（相对路径形式）。以 / 或盘符开头的绝对路径、"
                    "以及解析后落在授权目录之外的路径会被拒绝"
                ),
            ),
            ToolParam(
                name="content",
                type="string",
                required=True,
                description=(
                    "要写入的文本内容（UTF-8 文本，≤ 1MB）。write 时允许空字符串（创建空文件）；"
                    "文件不存在则创建（含父目录），已存在则覆盖；read 时忽略此参数"
                ),
            ),
        ],
        params_summary="action（必填）、path（必填）、content（write 必填）",
        usage_scenarios="读取、创建或修改授权目录内的文本文件（笔记、配置、代码、脚本等）。",
        input_requirements="路径为相对授权目录的相对路径；内容为 UTF-8 文本，单文件上限 1MB。",
        restrictions=(
            "仅能访问授权目录内（路径解析后不得逃逸）；本阶段仅支持文本文件；"
            "写入采用覆盖语义，无删除文件能力。"
        ),
        params_model=FileReadWriteParams,
    ),
}


def get_definition(name: str) -> ToolDefinition | None:
    """按注册表键查询工具定义（执行入口第 1 道检查）。"""
    return _REGISTRY.get(name)


def all_definitions() -> list[ToolDefinition]:
    """全部工具定义（按 name 排序，与列表接口排序一致）。"""
    return [_REGISTRY[name] for name in sorted(_REGISTRY)]


def is_registered(name: str) -> bool:
    """name 是否为注册表键。"""
    return name in _REGISTRY


def builtin_names() -> tuple[str, ...]:
    """全部注册表键（排序；迁移播种与测试夹具的取值来源）。"""
    return tuple(sorted(_REGISTRY))

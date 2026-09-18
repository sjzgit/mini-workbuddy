"""统一工具执行入口（FR-009~012，research R6）。

后续 Agent Loop 调用任何本地工具都经过 execute()：

    ① 注册表查 name      → 未命中：tool_not_found
    ② DB 查 enabled      → 无行视为未注册（tool_not_found）；停用：tool_disabled
    ③ 注册表模型校验参数  → 失败：invalid_params（逐项列出字段与原因）
    ④ 分发到工具实现      → ToolExecutionError 原样包装为结构化失败
    ⑤ 顶层 except 兜底    → execution_error，任何路径不向上抛异常（FR-012）

工具实现对 ToolExecutionError / ToolRunOutcome 的依赖方向是
"工具 → 本模块"，因此 dispatch 对工具模块做函数内延迟导入，避免循环。
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.schemas.tool import ToolExecutionResult, ToolErrorCode
from app.services import tool_registry, tool_service


class ToolExecutionError(Exception):
    """工具实现抛出的结构化失败（code + 人话 message + 可选 extra）。"""

    def __init__(
        self, code: ToolErrorCode, message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


@dataclass
class ToolRunOutcome:
    """工具实现的正常返回（成功或"命令执行失败"类业务结果）。"""

    success: bool
    output: str | None
    extra: dict[str, Any] = field(default_factory=dict)
    message: str | None = None  # None → 按成功/失败给默认文案


def execute(
    name: str, params: dict[str, Any], session: Session,
    *, shell_cwd: str | None = None,
) -> ToolExecutionResult:
    """统一执行入口：永不向上抛异常，失败也是结构化返回（FR-011/012）。

    shell_cwd（014）：shell 工具执行基准目录（运行时权限通过后由 Runtime 传入；
    直调场景缺省 None = 继承后端进程 cwd，与 003 既有行为一致）。
    """
    try:
        return _execute_checked(name, params, session, shell_cwd=shell_cwd)
    except ToolExecutionError as exc:
        return ToolExecutionResult(
            success=False,
            error_code=exc.code,
            message=exc.message,
            extra=exc.extra or None,
        )
    except Exception:  # noqa: BLE001 — 兜底：后端进程不崩溃，信息不泄露内部细节
        return ToolExecutionResult(
            success=False,
            error_code="execution_error",
            message="工具执行出错：发生未预期的内部错误，请检查输入后重试",
        )


def _execute_checked(
    name: str, params: dict[str, Any], session: Session,
    *, shell_cwd: str | None = None,
) -> ToolExecutionResult:
    # ① 存在性：注册表
    definition = tool_registry.get_definition(name)
    if definition is None:
        return _failure("tool_not_found", f"工具不存在或未注册：{name}")

    # ② 启停：tools 表（无行 = 未播种/被清空，视为未注册）
    enabled = tool_service.get_enabled(session, name)
    if enabled is None:
        return _failure("tool_not_found", f"工具不存在或未注册：{name}")
    if not enabled:
        return _failure(
            "tool_disabled",
            f"工具已停用：{definition.display_name}。可在工具管理页启用",
        )

    # ③ 参数：注册表校验模型（含多余参数拦截）
    try:
        validated = definition.params_model(**params)
    except ValidationError as exc:
        return _failure("invalid_params", _format_validation_error(exc))

    # ④ 分发（shell 透传执行基准目录；014）
    outcome = _dispatch(name, validated, shell_cwd=shell_cwd)
    return ToolExecutionResult(
        success=outcome.success,
        output=outcome.output,
        extra=outcome.extra or None,
        message=outcome.message
        or ("执行成功" if outcome.success else "执行失败"),
    )


def _dispatch(name: str, validated: BaseModel, *, shell_cwd: str | None = None) -> ToolRunOutcome:
    """分发到工具实现（延迟导入：工具模块反向依赖本模块的异常/结果类型）。

    ask_user 是运行内挂起语义（specs/013-ask-user-tool research R1/R6）：
    只能在 Agent 运行中由模型经 Runtime 调用，同步统一入口显式人话拒绝。
    每个 handler 只接受本工具的参数模型实例（注册表 params_model 派生），
    与 name 的对应关系由下方映射表保证，故参数类型用 ellipsis。
    """
    from app.services import file_tool, shell_tool, time_tool

    if name == "ask_user":
        raise ToolExecutionError(
            code="execution_error",
            message="ask_user 仅能在 Agent 运行中由模型调用，不支持直接执行",
        )

    handlers: dict[str, Callable[..., ToolRunOutcome]] = {
        tool_registry.CURRENT_TIME: time_tool.run,
        tool_registry.SHELL: lambda p: shell_tool.run(p, cwd=shell_cwd),
        tool_registry.FILE_READ_WRITE: file_tool.run,
    }
    handler = handlers.get(name)
    if handler is None:
        raise ToolExecutionError(
            code="execution_error", message=f"工具 {name} 尚未实现",
        )
    return handler(validated)


def _failure(code: ToolErrorCode, message: str) -> ToolExecutionResult:
    return ToolExecutionResult(
        success=False, error_code=code, message=message,
    )


def _format_validation_error(exc: ValidationError) -> str:
    """Pydantic 校验错误 → 人话"字段：原因"列表（不含内部细节）。"""
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(piece) for piece in error.get("loc", ()))
        reason = str(error.get("msg", "参数不合法")).removeprefix("Value error, ")
        parts.append(f"{location}：{reason}" if location else reason)
    return f"参数不符合要求：{'；'.join(parts)}"

"""shell 工具实现（FR-015~017，research R3/R4）。

执行链：危险命令拦截（执行层，先于 subprocess）→ subprocess（超时上限，
支持执行基准目录 cwd）→ 输出合并解码 → 截断 → 退出码语义。
014 安全边界：cwd 与命令中显式路径参数经运行时权限检查（run_tool 权限阶段）；
这是**应用层命令路径检查**，命令执行体的间接访问不在检查范围，不是 OS 级
沙箱——预留未来 ExecutionBackend 替换底座（契约 §4.2）。
退出码非 0 是正常业务结果（success=false + exit_code），不算系统错误。
"""

import locale
import subprocess

from app.core.config import settings
from app.services import danger_rules
from app.services.tool_executor import ToolExecutionError, ToolRunOutcome
from app.services.tool_registry import ShellParams

TRUNCATION_SUFFIX = "\n…[输出已截断]"


def run(params: ShellParams, cwd: str | None = None) -> ToolRunOutcome:
    """执行命令并返回输出与执行状态；危险命令在执行前拦截（FR-016）。

    cwd：执行基准目录（014 新增可选参数；缺省 None = 继承后端进程 cwd，
    与 003 既有行为一致）。运行时授权判定由 run_tool 权限检查阶段完成（014）。
    """
    category = danger_rules.check(params.command)
    if category is not None:
        raise ToolExecutionError(
            code="dangerous_command_blocked",
            message=danger_rules.block_message(category),
            extra={"blocked_category": category},
        )

    try:
        completed = subprocess.run(
            params.command,
            shell=True,
            capture_output=True,
            timeout=settings.shell_timeout_seconds,
            check=False,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolExecutionError(
            code="command_timeout",
            message=(
                f"命令执行超过 {settings.shell_timeout_seconds} 秒已被终止。"
                "请缩小命令范围或拆分执行"
            ),
        ) from exc

    output = _decode(completed.stdout, completed.stderr)
    output, truncated = _truncate(output, settings.shell_output_max_chars)
    success = completed.returncode == 0
    return ToolRunOutcome(
        success=success,
        output=output,
        extra={"exit_code": completed.returncode, "truncated": truncated},
        message="命令执行成功" if success
        else f"命令执行失败（退出码 {completed.returncode}）",
    )


def _decode(*chunks: bytes) -> str:
    """合并 stdout/stderr：UTF-8 优先，失败回退系统区域编码（errors=replace）。"""
    fallback = locale.getpreferredencoding(False) or "utf-8"
    parts: list[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        try:
            parts.append(chunk.decode("utf-8"))
        except UnicodeDecodeError:
            parts.append(chunk.decode(fallback, errors="replace"))
    return "\n".join(parts)


def _truncate(output: str, limit: int) -> tuple[str, bool]:
    """超过上限截断并加标记（FR-017）。"""
    if len(output) <= limit:
        return output, False
    return output[:limit] + TRUNCATION_SUFFIX, True

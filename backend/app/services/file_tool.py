"""file_read_write 工具实现（003 FR-018~020 + 014 权限职责上移，research R2）。

014 起：运行时授权判定（系统 ∪ 会话工作空间 ∪ 临时授权的三值判定）唯一入口是
agent_runtime.tools.run_tool 的权限检查阶段——工具层不做运行时权限拒绝
（Invariant 2/9）。相对路径语义不变：相对系统授权目录（003 契约）；
绝对路径直接解析，交由运行时判定。
"""

from pathlib import Path

from app.core.config import settings
from app.services.tool_executor import ToolExecutionError, ToolRunOutcome
from app.services.tool_registry import FileReadWriteParams

ENCODING = "utf-8"


def run(params: FileReadWriteParams) -> ToolRunOutcome:
    target = _resolve_within_root(params.path)
    if params.action == "read":
        return _read(target, params.path)
    return _write(target, params.path, params.content if params.content is not None else "")


def _resolve_within_root(path_str: str) -> Path:
    """解析目标路径：相对路径按系统授权目录拼接；绝对路径原样解析（不判定）。

    运行时授权判定由 run_tool 权限检查阶段统一完成（014 Invariant 2/9）；
    resolve() 展开 `..` 并穿透符号链接，与 PathResolver 同算法。
    """
    root = Path(settings.authorized_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)  # 授权目录不存在时自动创建
    candidate = Path(path_str)
    if candidate.is_absolute():
        return candidate.resolve()
    return (root / candidate).resolve()


def _read(target: Path, display_path: str) -> ToolRunOutcome:
    if not target.exists():
        raise ToolExecutionError(
            code="file_not_found",
            message=f"文件不存在：{display_path}",
        )
    if target.is_dir():
        raise ToolExecutionError(
            code="execution_error",
            message=f"目标是目录而非文件：{display_path}",
        )
    if target.stat().st_size > settings.file_max_bytes:
        raise ToolExecutionError(
            code="file_too_large",
            message=f"文件超过 {settings.file_max_bytes} 字节上限：{display_path}",
        )
    try:
        content = target.read_text(encoding=ENCODING)
    except UnicodeDecodeError as exc:
        raise ToolExecutionError(
            code="file_not_text",
            message=f"文件不是可读的 UTF-8 文本：{display_path}。本阶段仅支持文本文件",
        ) from exc
    return ToolRunOutcome(
        success=True,
        output=content,
        extra={"path": str(target)},
        message=f"已读取 {display_path}",
    )


def _write(target: Path, display_path: str, content: str) -> ToolRunOutcome:
    if len(content.encode(ENCODING)) > settings.file_max_bytes:
        raise ToolExecutionError(
            code="file_too_large",
            message=(
                f"写入内容超过 {settings.file_max_bytes} 字节上限：{display_path}"
            ),
        )
    target.parent.mkdir(parents=True, exist_ok=True)  # 父目录不存在自动创建
    target.write_text(content, encoding=ENCODING)  # 同名文件覆盖（参数说明声明）
    return ToolRunOutcome(
        success=True,
        output=None,
        extra={"path": str(target)},
        message=f"已写入 {display_path}",
    )

"""file_read_write 工具实现（FR-018~020，research R5）。

路径校验：(root / path).resolve() 后必须仍在授权目录内（is_relative_to），
统一拦截绝对路径、盘符路径与 .. 穿越后的逃逸；授权目录首次使用自动创建。
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
    root = Path(settings.authorized_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)  # 授权目录不存在时自动创建
    target = (root / path_str).resolve()
    if not target.is_relative_to(root):
        raise ToolExecutionError(
            code="path_outside_root",
            message=f"路径超出授权目录：{path_str}。仅允许访问授权目录内的相对路径",
        )
    return target


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

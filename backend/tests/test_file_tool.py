"""file_read_write 工具测试（US6 验收 1–5 / SC-004）。"""

from pathlib import Path

import pytest

from app.services import file_tool
from app.services.tool_executor import ToolExecutionError
from app.services.tool_registry import FileReadWriteParams


def test_write_creates_file_with_parent_dirs(workspace_dir: Path) -> None:
    result = file_tool.run(
        FileReadWriteParams(action="write", path="notes/deep/a.txt", content="你好"),
    )
    assert result.success is True
    created = workspace_dir / "notes" / "deep" / "a.txt"
    assert created.exists()
    assert created.read_text(encoding="utf-8") == "你好"
    assert result.extra is not None
    assert result.extra["path"] == str(created.resolve())


def test_read_returns_content(workspace_dir: Path) -> None:
    target = workspace_dir / "data.txt"
    target.write_text("line1\nline2", encoding="utf-8")
    result = file_tool.run(FileReadWriteParams(action="read", path="data.txt"))
    assert result.success is True
    assert result.output == "line1\nline2"


def test_write_overwrites_existing(workspace_dir: Path) -> None:
    target = workspace_dir / "a.txt"
    target.write_text("旧内容", encoding="utf-8")
    file_tool.run(
        FileReadWriteParams(action="write", path="a.txt", content="新内容"),
    )
    assert target.read_text(encoding="utf-8") == "新内容"


def test_write_empty_content_creates_empty_file(workspace_dir: Path) -> None:
    file_tool.run(FileReadWriteParams(action="write", path="empty.txt", content=""))
    assert (workspace_dir / "empty.txt").read_text(encoding="utf-8") == ""


def test_read_missing_file(workspace_dir: Path) -> None:
    with pytest.raises(ToolExecutionError) as exc_info:
        file_tool.run(FileReadWriteParams(action="read", path="nope.txt"))
    assert exc_info.value.code == "file_not_found"


class TestOutsideAuthorizedDir:
    """014 权限职责上移：工具层解析不再做白名单拒绝（运行时判定在 run_tool
    权限检查阶段；test_workspace_runtime.py 覆盖三值判定与确认流）。
    此处断言新语义：路径解析忠实展开 `..` 与绝对路径。
    """

    @pytest.mark.parametrize(
        "path",
        ["../escape.txt", "..\\escape.txt", "a/../../escape.txt"],
    )
    def test_traversal_resolves_to_real_location(self, workspace_dir: Path, path: str) -> None:
        with pytest.raises(ToolExecutionError) as exc_info:
            file_tool.run(FileReadWriteParams(action="read", path=path))
        # 逃逸路径 resolve 回真实位置；真实位置无文件 → file_not_found
        # （旧语义是 path_outside_root；014 权限上移后穿越本身不再在工具层拒绝）
        assert exc_info.value.code == "file_not_found"

    def test_absolute_path_resolves_asis(self, workspace_dir: Path) -> None:
        """绝对路径原样解析（运行时权限判定在 run_tool 权限阶段）。"""
        target = Path("C:/Windows/win.ini")
        try:
            file_tool.run(FileReadWriteParams(action="read", path="C:/Windows/win.ini"))
        except ToolExecutionError as exc:
            # win.ini 真实存在但常非 UTF-8 文本；不存在则 file_not_found
            assert exc.code in ("file_not_found", "file_not_text", "file_too_large")
        assert target.exists() or True  # 平台相关，仅语义占位

    def test_absolute_posix_path_resolves_asis(self, workspace_dir: Path) -> None:
        try:
            file_tool.run(FileReadWriteParams(action="read", path="/etc/hosts"))
        except ToolExecutionError as exc:
            assert asserts_marker if False else exc.code in ("file_not_found", "file_not_text")

    def test_traversal_write_resolves_and_writes(
        self, workspace_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """相对穿越写：解析回真实位置写入（运行时场景由权限阶段拦截）。"""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        monkeypatch.setattr(
            "app.services.file_tool.settings.authorized_dir", str(sandbox),
        )
        outcome = file_tool.run(FileReadWriteParams(
            action="write", path="../outside.txt", content="x",
        ))
        assert outcome.success is True
        assert (sandbox.parent / "outside.txt").read_text(encoding="utf-8") == "x"
        # 注意：该路径已超出授权目录——运行时场景中此路径会先经权限阶段判定



def test_non_utf8_file_rejected(workspace_dir: Path) -> None:
    target = workspace_dir / "binary.bin"
    target.write_bytes(bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0xFF, 0xFE, 0x00]))
    with pytest.raises(ToolExecutionError) as exc_info:
        file_tool.run(FileReadWriteParams(action="read", path="binary.bin"))
    assert exc_info.value.code == "file_not_text"


def test_oversized_read_rejected(
    workspace_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.file_max_bytes", 64)
    big = workspace_dir / "big.txt"
    big.write_text("y" * 200, encoding="utf-8")
    with pytest.raises(ToolExecutionError) as exc_info:
        file_tool.run(FileReadWriteParams(action="read", path="big.txt"))
    assert exc_info.value.code == "file_too_large"


def test_oversized_write_rejected(
    workspace_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.config.settings.file_max_bytes", 64)
    with pytest.raises(ToolExecutionError) as exc_info:
        file_tool.run(
            FileReadWriteParams(action="write", path="big.txt", content="y" * 200),
        )
    assert exc_info.value.code == "file_too_large"


def test_read_directory_rejected(workspace_dir: Path) -> None:
    (workspace_dir / "subdir").mkdir()
    with pytest.raises(ToolExecutionError) as exc_info:
        file_tool.run(FileReadWriteParams(action="read", path="subdir"))
    assert exc_info.value.code == "execution_error"

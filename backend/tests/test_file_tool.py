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
    @pytest.mark.parametrize(
        "path",
        ["../escape.txt", "..\\escape.txt", "a/../../escape.txt"],
    )
    def test_traversal_rejected(self, workspace_dir: Path, path: str) -> None:
        with pytest.raises(ToolExecutionError) as exc_info:
            file_tool.run(FileReadWriteParams(action="read", path=path))
        assert exc_info.value.code == "path_outside_root"

    def test_absolute_posix_path_rejected(self, workspace_dir: Path) -> None:
        with pytest.raises(ToolExecutionError) as exc_info:
            file_tool.run(FileReadWriteParams(action="read", path="/etc/hosts"))
        assert exc_info.value.code == "path_outside_root"

    def test_windows_drive_path_rejected(self, workspace_dir: Path) -> None:
        with pytest.raises(ToolExecutionError) as exc_info:
            file_tool.run(
                FileReadWriteParams(action="read", path="C:/Windows/win.ini"),
            )
        assert exc_info.value.code == "path_outside_root"

    def test_traversal_write_rejected(self, workspace_dir: Path) -> None:
        with pytest.raises(ToolExecutionError) as exc_info:
            file_tool.run(
                FileReadWriteParams(
                    action="write", path="../outside.txt", content="x",
                ),
            )
        assert exc_info.value.code == "path_outside_root"


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

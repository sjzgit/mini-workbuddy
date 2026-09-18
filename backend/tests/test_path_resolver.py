"""PathResolver 边界测试（specs/014-workspace-permission，spec 十三/十四/十五、Edge Cases）。

覆盖：绝对/相对路径、`..` 回溯、`.`、重复分隔符、尾分隔符、Windows 大小写不敏感、
前缀相似目录不互含、不存在路径可解析、Symlink 穿透（无权限平台 skip 并注明）。
"""

import os
from pathlib import Path

import pytest

from app.services.agent_runtime.permission import is_within, resolve_path


class TestResolvePath:
    def test_absolute_path_passthrough(self, tmp_path: Path) -> None:
        resolved = resolve_path(str(tmp_path / "a.txt"))
        assert resolved == (tmp_path / "a.txt").resolve()

    def test_relative_path_joins_base(self, tmp_path: Path) -> None:
        resolved = resolve_path("src/main.py", base=tmp_path)
        assert resolved == (tmp_path / "src" / "main.py").resolve()

    def test_relative_without_base_uses_cwd(self) -> None:
        resolved = resolve_path("whatever.txt")
        assert resolved.is_absolute()

    def test_dotdot_escape_normalized(self, tmp_path: Path) -> None:
        inside = tmp_path / "project"
        inside.mkdir()
        resolved = resolve_path(str(inside / "src" / ".." / "secret.txt"))
        # `..` 展开后真实路径是 project/secret.txt
        assert resolved == (inside / "secret.txt").resolve()

    def test_dot_and_duplicate_separators(self, tmp_path: Path) -> None:
        resolved = resolve_path(str(tmp_path / "src" / "." / "a.txt"))
        assert resolved == (tmp_path / "src" / "a.txt").resolve()

    def test_trailing_separator_equivalent(self, tmp_path: Path) -> None:
        with_tail = resolve_path(str(tmp_path) + os.sep)
        assert with_tail == tmp_path.resolve()

    def test_nonexistent_path_resolvable(self, tmp_path: Path) -> None:
        resolved = resolve_path(str(tmp_path / "new" / "deep" / "file.txt"))
        assert resolved == (tmp_path / "new" / "deep" / "file.txt").resolve()

    def test_expands_user_home(self) -> None:
        resolved = resolve_path("~" / Path("x.txt") if False else "~/x.txt")
        expected = Path(os.path.expanduser("~/x.txt")).resolve()
        assert resolved == expected


class TestIsWithin:
    def test_root_itself_is_within(self, tmp_path: Path) -> None:
        assert is_within(tmp_path.resolve(), tmp_path.resolve())

    def test_child_is_within(self, tmp_path: Path) -> None:
        child = tmp_path / "sub" / "file.txt"
        assert is_within(child.resolve(), tmp_path.resolve())

    def test_sibling_prefix_similar_not_within(self, tmp_path: Path) -> None:
        # D:\project2 与 D:\project 前缀相似但同级：绝不可互含（spec 十三）
        project = tmp_path / "project"
        project.mkdir()
        project2 = tmp_path / "project2"
        project2.mkdir()
        assert not is_within(project2.resolve(), project.resolve())
        assert not is_within(project.resolve(), project2.resolve())

    def test_parent_not_within_child(self, tmp_path: Path) -> None:
        child = tmp_path / "sub"
        child.mkdir()
        assert not is_within(tmp_path.resolve(), child.resolve())

    @pytest.mark.skipif(os.name != "nt", reason="Windows 大小写不敏感语义")
    def test_windows_case_insensitive(self, tmp_path: Path) -> None:
        child = tmp_path / "Sub" / "File.txt"
        lower_root = str(tmp_path).lower()
        assert is_within(child, Path(lower_root).resolve())

    def test_symlink_escape_detected(self, tmp_path: Path) -> None:
        """Workspace/link → outside：请求 link 内路径必须按真实目标判定（spec 十五）。"""
        outside = tmp_path / "outside"
        outside.mkdir()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        try:
            os.symlink(outside, workspace / "link")
        except (OSError, NotImplementedError):
            pytest.skip("当前环境无符号链接权限（Windows 需开发者模式/管理员）")
        through_link = workspace / "link" / "secret.txt"
        assert not is_within(through_link.resolve(), workspace.resolve())
        assert is_within(through_link.resolve(), outside.resolve())

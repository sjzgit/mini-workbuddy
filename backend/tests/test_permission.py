"""PermissionManager 三值判定测试（specs/014-workspace-permission，spec FR-008/011/015）。

覆盖：系统/会话工作空间 ALLOW、并集、范围外 ASK_USER、临时授权、保护集优先 DENY、
授权目录覆盖子树、grant 不跨上下文（新上下文重新 ASK）。
"""

from pathlib import Path

from app.core.config import settings
from app.services.agent_runtime.permission import (
    DECISION_ALLOW,
    DECISION_ASK_USER,
    DECISION_DENY,
    PermissionManager,
    RunPermissionContext,
    TemporaryGrant,
    build_context,
    is_within,
    resolve_path,
)


def _ctx(tmp_path: Path, session: Path | None = None) -> RunPermissionContext:
    return build_context(tmp_path / "system", session)


class TestCheckBasics:
    def test_system_workspace_allows(self, tmp_path: Path) -> None:
        ctx = _ctx(tmp_path)
        target = resolve_path("a.txt", base=ctx.system_root)
        decision = PermissionManager.check(target, ctx)
        assert decision.decision == DECISION_ALLOW

    def test_session_workspace_allows(self, tmp_path: Path) -> None:
        session = tmp_path / "project"
        session.mkdir()
        ctx = _ctx(tmp_path, session)
        target = session / "src" / "main.py"
        assert PermissionManager.check(target, ctx).decision == DECISION_ALLOW

    def test_union_of_both_workspaces(self, tmp_path: Path) -> None:
        session = tmp_path / "project"
        session.mkdir()
        ctx = _ctx(tmp_path, session)
        assert PermissionManager.check(ctx.system_root / "a.txt", ctx).decision == DECISION_ALLOW
        assert PermissionManager.check(session / "b.txt", ctx).decision == DECISION_ALLOW

    def test_outside_asks_user(self, tmp_path: Path) -> None:
        ctx = _ctx(tmp_path)
        outside = tmp_path / "other" / "a.txt"
        decision = PermissionManager.check(outside, ctx)
        assert decision.decision == DECISION_ASK_USER
        assert decision.error_code is None
        assert "工作空间之外" in decision.reason

    def test_no_session_root_attribute(self, tmp_path: Path) -> None:
        """未选择工作空间（session_root=None）时系统目录仍 ALLOW、外部 ASK。"""
        ctx = _ctx(tmp_path, None)
        assert ctx.session_root is None
        assert PermissionManager.check(ctx.system_root / "x", ctx).decision == DECISION_ALLOW
        assert PermissionManager.check(tmp_path / "elsewhere", ctx).decision == DECISION_ASK_USER


class TestTemporaryGrant:
    def test_grant_allows_exact_path(self, tmp_path: Path) -> None:
        ctx = _ctx(tmp_path)
        outside = tmp_path / "other" / "a.txt"
        ctx.grants.append(TemporaryGrant(path=str(outside.resolve())))
        assert PermissionManager.check(outside, ctx).decision == DECISION_ALLOW

    def test_grant_directory_covers_subtree(self, tmp_path: Path) -> None:
        ctx = _ctx(tmp_path)
        grant_dir = tmp_path / "other"
        ctx.grants.append(TemporaryGrant(path=str(grant_dir.resolve())))
        assert PermissionManager.check(grant_dir / "deep" / "f.txt", ctx).decision == DECISION_ALLOW

    def test_grant_scoped_to_context(self, tmp_path: Path) -> None:
        """新运行 = 新上下文（空 grants）→ 同路径重新 ASK（Invariant 5 / FR-023）。"""
        outside = tmp_path / "other" / "a.txt"
        granted = _ctx(tmp_path)
        granted.grants.append(TemporaryGrant(path=str(outside.resolve())))
        fresh = _ctx(tmp_path)
        assert PermissionManager.check(outside, granted).decision == DECISION_ALLOW
        assert PermissionManager.check(outside, fresh).decision == DECISION_ASK_USER


class TestProtectedPaths:
    def test_protected_denies_even_inside_workspace(self, tmp_path: Path) -> None:
        """保护集优先级最高：会话工作空间包含保护目录也 DENY（Invariant 8）。"""
        session = tmp_path / "project"
        protected_dir = session / "c-windows"  # 模拟被误设进工作空间的保护目录
        protected_dir.mkdir(parents=True)
        ctx = build_context(
            tmp_path / "system", session,
        )
        ctx.protected = [protected_dir.resolve()]
        decision = PermissionManager.check(protected_dir / "win.ini", ctx)
        assert decision.decision == DECISION_DENY
        assert decision.error_code == "system_protected_path"

    def test_windows_system_dir_denied_by_default(self, monkeypatch, tmp_path: Path) -> None:
        """默认保护集含 C:\\Windows（Windows 平台真实断言）。"""
        ctx = _ctx(tmp_path)
        target = Path(r"C:\Windows")
        decision = PermissionManager.check(target, ctx)
        assert decision.decision == DECISION_DENY

    def test_protected_checked_before_grant(self, tmp_path: Path) -> None:
        """先 DENY 后授权判断：保护路径不允许通过 grant 放行（Invariant 8）。"""
        ctx = _ctx(tmp_path)
        ctx.protected = [(tmp_path / "vault").resolve()]
        ctx.grants.append(TemporaryGrant(path=str((tmp_path / "vault" / "k.txt").resolve())))
        decision = PermissionManager.check(tmp_path / "vault" / "k.txt", ctx)
        assert decision.decision == DECISION_DENY

    def test_extra_protected_from_settings(self, tmp_path: Path, monkeypatch) -> None:
        """settings.protected_paths（os.pathsep 分隔）并入保护集（FR-015 可配置）。"""
        monkeypatch.setattr(
            settings, "protected_paths",
            os_pathsep_join(tmp_path / "custom-a", tmp_path / "custom-b"),
        )
        ctx = _ctx(tmp_path)
        assert is_within(tmp_path / "custom-a" / "x", ctx.protected[0]) or any(
            p == (tmp_path / "custom-a").resolve() for p in ctx.protected
        )
        assert PermissionManager.check(tmp_path / "custom-b" / "y", ctx).decision == DECISION_DENY


def os_pathsep_join(*paths: Path) -> str:
    import os

    return os.pathsep.join(str(p) for p in paths)

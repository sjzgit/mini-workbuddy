"""WorkspaceManager 全场景测试（specs/014-workspace-permission，US1；spec FR-001~007）。

覆盖：设置/更换/清除、持久化、会话隔离、相对/不存在/文件路径/保护目录拒绝、
busy（生成中）仍可设置。目录用 tmp_path 真实创建（Windows 本机断言）。
"""

from pathlib import Path

import pytest

from app.models import ConversationEntry
from app.services.workspace_service import (
    WorkspaceError,
    clear_workspace,
    get_workspace,
    set_workspace,
)


@pytest.fixture
def conversation(db_session, seed_agent) -> ConversationEntry:
    entry = ConversationEntry(title="工作空间测试", agent_id=seed_agent.id)
    db_session.add(entry)
    db_session.commit()
    return entry


class TestSetWorkspace:
    def test_set_and_get(self, db_session, conversation, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        out = set_workspace(db_session, conversation.id, str(workspace))
        assert out.workspace_path == str(workspace.resolve())
        got = get_workspace(db_session, conversation.id)
        assert got.workspace_path == str(workspace.resolve())
        assert got.workspace_source == "user_selected"
        assert got.workspace_selected_at is not None

    def test_replace(self, db_session, conversation, tmp_path: Path) -> None:
        first_dir = tmp_path / "first"
        first_dir.mkdir()
        second_dir = tmp_path / "second"
        second_dir.mkdir()
        set_workspace(db_session, conversation.id, str(first_dir))
        out = set_workspace(db_session, conversation.id, str(second_dir))
        assert out.workspace_path == str(second_dir.resolve())
        assert get_workspace(db_session, conversation.id).workspace_path == str(
            second_dir.resolve(),
        )

    def test_persists_across_requery(self, db_session, conversation, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        set_workspace(db_session, conversation.id, str(workspace))
        db_session.expire_all()  # 强制从库重载：证明值已持久化
        got = get_workspace(db_session, conversation.id)
        assert got.workspace_path == str(workspace.resolve())

    def test_different_conversations_isolated(
        self, db_session, seed_agent, tmp_path: Path,
    ) -> None:
        conv_a = ConversationEntry(title="A", agent_id=seed_agent.id)
        conv_b = ConversationEntry(title="B", agent_id=seed_agent.id)
        db_session.add_all([conv_a, conv_b])
        db_session.commit()
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        dir_b = tmp_path / "b"
        dir_b.mkdir()
        set_workspace(db_session, conv_a.id, str(dir_a))
        set_workspace(db_session, conv_b.id, str(dir_b))
        assert get_workspace(db_session, conv_a.id).workspace_path == str(dir_a.resolve())
        assert get_workspace(db_session, conv_b.id).workspace_path == str(dir_b.resolve())

    def test_relative_path_rejected(self, db_session, conversation) -> None:
        with pytest.raises(WorkspaceError, match="绝对路径"):
            set_workspace(db_session, conversation.id, "relative/dir")

    def test_nonexistent_rejected(self, db_session, conversation) -> None:
        with pytest.raises(WorkspaceError, match="不存在"):
            set_workspace(db_session, conversation.id, "D:\\no-such-dir-014")

    def test_file_not_dir_rejected(self, db_session, conversation, tmp_path: Path) -> None:
        file_path = tmp_path / "file.txt"
        file_path.write_text("x", encoding="utf-8")
        with pytest.raises(WorkspaceError, match="不是目录"):
            set_workspace(db_session, conversation.id, str(file_path))

    def test_protected_rejected(self, db_session, conversation) -> None:
        with pytest.raises(WorkspaceError, match="保护"):
            set_workspace(db_session, conversation.id, "C:\\Windows")

    def test_clear_then_get_none(self, db_session, conversation, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        set_workspace(db_session, conversation.id, str(workspace))
        out = clear_workspace(db_session, conversation.id)
        assert out.workspace_path is None
        assert out.workspace_source is None
        assert out.workspace_selected_at is None

    def test_clear_idempotent(self, db_session, conversation) -> None:
        out = clear_workspace(db_session, conversation.id)  # 未设置过：幂等成功
        assert out.workspace_path is None

    def test_busy_still_allows_set(
        self, db_session, conversation, tmp_path: Path,
    ) -> None:
        """生成中允许设置（快照语义，spec 二十八）：workspace_service 无 busy 拦截。"""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        set_workspace(db_session, conversation.id, str(workspace))
        assert get_workspace(db_session, conversation.id).workspace_path is not None

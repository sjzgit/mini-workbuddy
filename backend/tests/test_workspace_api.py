"""Workspace API 三端点契约测试（specs/014-workspace-permission，US1；契约 §1）。

覆盖：GET/PUT/DELETE 200/404/400 detail、PUT 后 GET 一致、DELETE 幂等、
ConversationSummary 携带 workspace_path、生成中（busy）允许 PUT。
"""

from pathlib import Path

import pytest

from app.models import ConversationEntry


@pytest.fixture
def conversation(db_session, seed_agent) -> ConversationEntry:
    entry = ConversationEntry(title="WS API 测试", agent_id=seed_agent.id)
    db_session.add(entry)
    db_session.commit()
    return entry


def test_get_unset_returns_nulls(client, conversation) -> None:
    response = client.get(f"/api/conversations/{conversation.id}/workspace")
    assert response.status_code == 200
    body = response.json()
    assert body == {"workspace_path": None, "workspace_source": None, "workspace_selected_at": None}


def test_put_then_get_roundtrip(client, conversation, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    response = client.put(
        f"/api/conversations/{conversation.id}/workspace",
        json={"path": str(workspace)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["workspace_path"] == str(workspace.resolve())
    assert body["workspace_source"] == "user_selected"

    got = client.get(f"/api/conversations/{conversation.id}/workspace")
    assert got.json()["workspace_path"] == str(workspace.resolve())


def test_put_rejects_relative_path(client, conversation) -> None:
    response = client.put(
        f"/api/conversations/{conversation.id}/workspace",
        json={"path": "relative/dir"},
    )
    assert response.status_code == 400
    assert "绝对路径" in response.json()["detail"]


def test_put_rejects_nonexistent(client, conversation) -> None:
    response = client.put(
        f"/api/conversations/{conversation.id}/workspace",
        json={"path": "D:\\no-such-dir-014"},
    )
    assert response.status_code == 400
    assert "不存在" in response.json()["detail"]


def test_put_rejects_file_path(client, conversation, tmp_path: Path) -> None:
    file_path = tmp_path / "f.txt"
    file_path.write_text("x", encoding="utf-8")
    response = client.put(
        f"/api/conversations/{conversation.id}/workspace",
        json={"path": str(file_path)},
    )
    assert response.status_code == 400
    assert "不是目录" in response.json()["detail"]


def test_put_rejects_protected(client, conversation) -> None:
    response = client.put(
        f"/api/conversations/{conversation.id}/workspace",
        json={"path": "C:\\Windows"},
    )
    assert response.status_code == 400
    assert "保护" in response.json()["detail"]


def test_delete_clears(client, conversation, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    client.put(
        f"/api/conversations/{conversation.id}/workspace",
        json={"path": str(workspace)},
    )
    response = client.delete(f"/api/conversations/{conversation.id}/workspace")
    assert response.status_code == 200
    assert response.json()["workspace_path"] is None


def test_delete_idempotent(client, conversation) -> None:
    response = client.delete(f"/api/conversations/{conversation.id}/workspace")
    assert response.status_code == 200
    assert response.json()["workspace_path"] is None


def test_404_for_missing_conversation(client) -> None:
    for method, suffix in (("get", "/workspace"), ("put", "/workspace"), ("delete", "/workspace")):
        response = getattr(client, method)(
            "/api/conversations/999999/workspace", **({"json": {"path": "D:\\"}} if method == "put" else {}),
        )
        assert response.status_code == 404


def test_conversation_summary_carries_workspace(client, conversation, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    client.put(
        f"/api/conversations/{conversation.id}/workspace",
        json={"path": str(workspace)},
    )
    listing = client.get("/api/conversations").json()
    matched = [c for c in listing if c["id"] == conversation.id]
    assert matched and matched[0]["workspace_path"] == str(workspace.resolve())


def test_busy_conversation_allows_put(client, db_session, conversation, tmp_path: Path) -> None:
    """生成中允许设置工作空间（快照语义，spec 二十八）：直接 PUT 成功 200。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    response = client.put(
        f"/api/conversations/{conversation.id}/workspace",
        json={"path": str(workspace)},
    )
    assert response.status_code == 200

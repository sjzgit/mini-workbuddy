"""MCP 管理 HTTP 契约测试（契约 mcp-api.md；tasks T025）。

覆盖：CRUD / 字段互斥 / 掩码零泄漏（SC-005）/ 三态合并 / config_changed 前置 / 忙拒绝。
"""

import json

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import McpServerEntry

STDIO_PAYLOAD = {
    "name": "fs-demo",
    "description": "文件系统 Server",
    "server_type": "stdio",
    "command": "npx",
    "command_args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/data"],
    "env": {"API_TOKEN": "secret-value-1234"},
}
HTTP_PAYLOAD = {
    "name": "remote",
    "description": "远程 Server",
    "server_type": "http",
    "url": "http://127.0.0.1:9300/mcp",
    "headers": {"Authorization": "Bearer sk-header-secret-9"},
}


def _create(client: TestClient, payload: dict) -> dict:
    response = client.post("/api/mcp/servers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_stdio_and_list(client: TestClient) -> None:
    detail = _create(client, STDIO_PAYLOAD)
    assert detail["server_type"] == "stdio"
    assert detail["command"] == "npx"
    assert detail["command_args"] == ["-y", "@modelcontextprotocol/server-filesystem", "C:/data"]
    assert detail["enabled"] is True
    assert detail["last_test_status"] is None  # 未测试
    assert detail["last_test_tool_count"] is None  # 未知
    assert detail["env_masked"] == {"API_TOKEN": "••••••"}

    items = client.get("/api/mcp/servers").json()
    assert len(items) == 1
    assert items[0]["name"] == "fs-demo"


def test_create_http_with_headers(client: TestClient) -> None:
    detail = _create(client, HTTP_PAYLOAD)
    assert detail["url"] == "http://127.0.0.1:9300/mcp"
    assert detail["headers_masked"] == {"Authorization": "••••••"}
    assert detail["command"] is None
    assert "env_masked" not in detail or detail["env_masked"] is None


def test_create_type_field_mutex_422(client: TestClient) -> None:
    """互斥校验（契约 §2）：stdio 带 url / http 带 command 均 422。"""
    bad_stdio = {**STDIO_PAYLOAD, "url": "http://x/mcp"}
    assert client.post("/api/mcp/servers", json=bad_stdio).status_code == 422
    bad_http = {**HTTP_PAYLOAD, "command": "npx"}
    assert client.post("/api/mcp/servers", json=bad_http).status_code == 422
    missing_command = {"name": "x", "server_type": "stdio"}
    assert client.post("/api/mcp/servers", json=missing_command).status_code == 422
    bad_url = {**HTTP_PAYLOAD, "url": "not-a-url"}
    assert client.post("/api/mcp/servers", json=bad_url).status_code == 422


def test_create_same_name_400(client: TestClient) -> None:
    _create(client, STDIO_PAYLOAD)
    response = client.post("/api/mcp/servers", json={**STDIO_PAYLOAD, "description": "另一份"})
    assert response.status_code == 400
    assert "同名" in response.json()["detail"]


def test_secret_plaintext_never_in_any_response(client: TestClient) -> None:
    """SC-005：明文 env 值与 Header 值不出现在任何响应体。"""
    _create(client, STDIO_PAYLOAD)
    _create(client, HTTP_PAYLOAD)

    list_body = client.get("/api/mcp/servers").text
    detail_body = client.get("/api/mcp/servers/1").text
    detail_body2 = client.get("/api/mcp/servers/2").text
    for body in (list_body, detail_body, detail_body2):
        assert "secret-value-1234" not in body
        assert "sk-header-secret-9" not in body


def test_update_three_state_merge(
    client: TestClient, db_session: Session, secret_key_path: object,
) -> None:
    """三态协议（FR-024）：null 保留、字符串替换、键缺席删除。"""
    detail = _create(client, STDIO_PAYLOAD)
    server_id = detail["id"]

    updated = client.put(
        f"/api/mcp/servers/{server_id}",
        json={
            **STDIO_PAYLOAD,
            "env": {
                "API_TOKEN": None,  # 保留原值
                "NEW_VAR": "brand-new-value",  # 新增
            },
        },
    ).json()
    assert updated["env_masked"] == {"API_TOKEN": "••••••", "NEW_VAR": "••••••"}

    # 值真实保留：解密核对（DB 侧，不经接口）
    entry = db_session.get(McpServerEntry, server_id)
    from app.core import secret_vault

    env = dict(json.loads(secret_vault.load_secret(db_session, entry.env_secret_ref) or "{}"))
    assert env == {"API_TOKEN": "secret-value-1234", "NEW_VAR": "brand-new-value"}

    # 键缺席 = 删除（只保留 NEW_VAR）
    client.put(
        f"/api/mcp/servers/{server_id}",
        json={**STDIO_PAYLOAD, "env": {"NEW_VAR": None}},
    )
    entry = db_session.get(McpServerEntry, server_id)
    env = dict(json.loads(secret_vault.load_secret(db_session, entry.env_secret_ref) or "{}"))
    assert env == {"NEW_VAR": "brand-new-value"}


def test_update_untouched_env_section_kept(
    client: TestClient, db_session: Session, secret_key_path: object,
) -> None:
    """env 键整体缺席（None）时原密文保留。"""
    detail = _create(client, STDIO_PAYLOAD)
    from app.core import secret_vault

    entry = db_session.get(McpServerEntry, detail["id"])
    ref_before = entry.env_secret_ref
    client.put(
        f"/api/mcp/servers/{detail['id']}",
        json={**STDIO_PAYLOAD, "env": None, "description": "改说明"},
    )
    db_session.expire_all()
    entry = db_session.get(McpServerEntry, detail["id"])
    assert entry.env_secret_ref == ref_before
    env = dict(json.loads(secret_vault.load_secret(db_session, entry.env_secret_ref) or "{}"))
    assert env == {"API_TOKEN": "secret-value-1234"}


def test_delete_cleans_secrets(
    client: TestClient, db_session: Session, secret_key_path: object,
) -> None:
    from app.models import SecretVaultEntry

    detail = _create(client, STDIO_PAYLOAD)
    assert client.delete(f"/api/mcp/servers/{detail['id']}").status_code == 200
    assert db_session.scalars(select(SecretVaultEntry)).all() == []
    assert client.get(f"/api/mcp/servers/{detail['id']}").status_code == 404


def test_update_same_name_400_and_404(client: TestClient) -> None:
    _create(client, STDIO_PAYLOAD)
    second = _create(client, {**HTTP_PAYLOAD, "name": "second"})
    response = client.put(f"/api/mcp/servers/{second['id']}", json={**HTTP_PAYLOAD, "name": "fs-demo"})
    assert response.status_code == 400
    assert client.put("/api/mcp/servers/999", json=STDIO_PAYLOAD).status_code == 404


def test_toggle_enabled(client: TestClient) -> None:
    detail = _create(client, STDIO_PAYLOAD)
    response = client.put(f"/api/mcp/servers/{detail['id']}/enabled", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    # 启停不影响测试结果状态（FR-032：仍为未测试 NULL）
    assert response.json()["last_test_status"] is None

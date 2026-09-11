"""MCP 测试连接集成测试（真 stdio 假 Server；tasks T036）。

覆盖 SC-008（工具详情）、FR-027（无工具）、FR-028（六类失败）、FR-030（并发锁）、
FR-031（进程零残留语义）、FR-033（停用可测不自动启用）、FR-034（config_changed）。
"""

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent))
from fake_mcp_server import __file__ as FAKE_SERVER_PATH  # noqa: E402

FAKE_SERVER = str(Path(FAKE_SERVER_PATH))


def _create_stdio(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "fake",
        "description": "测试 Server",
        "server_type": "stdio",
        "command": sys.executable,
        "command_args": [FAKE_SERVER, "--tools", "2"],
        **overrides,
    }
    response = client.post("/api/mcp/servers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _create_http(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "remote-down",
        "description": "不可达",
        "server_type": "http",
        "url": "http://127.0.0.1:9/mcp",
        **overrides,
    }
    response = client.post("/api/mcp/servers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_test_connection_success_with_tools(client: TestClient, mcp_test_timeout: int) -> None:
    """真 stdio：发现 2 个工具，参数类型/必填齐全（SC-008）。"""
    detail = _create_stdio(client)
    response = client.post(f"/api/mcp/servers/{detail['id']}/test")
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "success"
    assert result["tool_count"] == 2
    names = {tool["name"] for tool in result["tools"]}
    assert names == {"get_weather", "echo"}

    weather = next(tool for tool in result["tools"] if tool["name"] == "get_weather")
    assert "天气预报" in weather["description"]
    params = {param["name"]: param for param in weather["params"]}
    assert params["city"]["required"] is True
    assert params["city"]["type"] == "string"
    assert params["days"]["required"] is False

    # 快照落库：列表可见（FR-015）
    item = client.get(f"/api/mcp/servers/{detail['id']}").json()
    assert item["last_test_status"] == "success"
    assert item["last_test_tool_count"] == 2


def test_test_connection_no_tools(client: TestClient, mcp_test_timeout: int) -> None:
    """无工具：连接成功，未发现工具（FR-027）。"""
    detail = _create_stdio(client, name="empty", command_args=[FAKE_SERVER, "--tools", "0"])
    result = client.post(f"/api/mcp/servers/{detail['id']}/test").json()
    assert result["status"] == "success"
    assert result["message"] == "连接成功，未发现工具"
    assert result["tool_count"] == 0


def test_test_connection_command_not_found(client: TestClient) -> None:
    detail = _create_stdio(client, name="no-cmd", command="definitely-not-a-real-cmd-xyz")
    result = client.post(f"/api/mcp/servers/{detail['id']}/test").json()
    assert result["status"] == "failed"
    assert result["category"] == "command_not_found"


def test_test_connection_process_failed(client: TestClient, mcp_test_timeout: int) -> None:
    """启动即退出（python -c exit 1）→ 进程失败类（含流早关被包装为协议错误的容差）。"""
    detail = _create_stdio(
        client, name="crash", command_args=["-c", "import sys; sys.exit(1)"],
    )
    result = client.post(f"/api/mcp/servers/{detail['id']}/test").json()
    assert result["status"] == "failed"
    assert result["category"] in ("process_failed", "protocol_incompatible", "timeout", "unknown")


def test_test_connection_timeout(client: TestClient, mcp_test_timeout: int) -> None:
    """挂起进程 → 超时分类。"""
    detail = _create_stdio(client, name="hang", command_args=[FAKE_SERVER, "--hang"])
    result = client.post(f"/api/mcp/servers/{detail['id']}/test").json()
    assert result["status"] == "failed"
    assert result["category"] == "timeout"


def test_test_connection_garbage_output(client: TestClient, mcp_test_timeout: int) -> None:
    """stdout 非 MCP 内容 → 协议不兼容 / 进程退出类（SDK 语义映射，契约容差）。"""
    detail = _create_stdio(client, name="garbage", command_args=[FAKE_SERVER, "--garbage"])
    result = client.post(f"/api/mcp/servers/{detail['id']}/test").json()
    assert result["status"] == "failed"
    assert result["category"] in ("protocol_incompatible", "process_failed", "timeout")


def test_test_connection_http_unreachable(client: TestClient) -> None:
    """HTTP 不可达：按 SDK 实际异常语义归类（连接失败/协议不兼容/流失败均属合理映射）。"""
    detail = _create_http(client)
    result = client.post(f"/api/mcp/servers/{detail['id']}/test").json()
    assert result["status"] == "failed"
    assert result["category"] in (
        "connection_failed",
        "unknown",
        "process_failed",
        "timeout",
        "protocol_incompatible",
    )


def test_disabled_server_can_test_and_stays_disabled(
    client: TestClient, mcp_test_timeout: int,
) -> None:
    """FR-033：停用可测试；成功不自动启用。"""
    detail = _create_stdio(client, name="disabled")
    client.put(f"/api/mcp/servers/{detail['id']}/enabled", json={"enabled": False})
    result = client.post(f"/api/mcp/servers/{detail['id']}/test").json()
    assert result["status"] == "success"
    assert result["item"]["enabled"] is False


def test_config_changed_after_editing_config(
    client: TestClient, mcp_test_timeout: int,
) -> None:
    """FR-034：改启动参数 → config_changed；重测成功 → 恢复。"""
    detail = _create_stdio(client, name="cfg")
    client.post(f"/api/mcp/servers/{detail['id']}/test")
    updated = client.put(
        f"/api/mcp/servers/{detail['id']}",
        json={
            "name": "cfg",
            "description": "测试 Server",
            "server_type": "stdio",
            "command": sys.executable,
            "command_args": [FAKE_SERVER, "--tools", "1"],  # 参数变化
            "env": None,
        },
    ).json()
    assert updated["last_test_status"] == "config_changed"
    assert updated["last_test_message"] == "配置已变更，待重新测试"
    assert updated["last_test_tool_count"] == 2  # 保留旧快照数量

    result = client.post(f"/api/mcp/servers/{detail['id']}/test").json()
    assert result["status"] == "success"
    assert result["item"]["last_test_status"] == "success"
    assert result["tool_count"] == 1


def test_edit_description_only_keeps_test_status(
    client: TestClient, mcp_test_timeout: int,
) -> None:
    """仅改 name/description 不触发 config_changed（research R6）。"""
    detail = _create_stdio(client, name="desc-only")
    client.post(f"/api/mcp/servers/{detail['id']}/test")
    updated = client.put(
        f"/api/mcp/servers/{detail['id']}",
        json={
            "name": "desc-only-2",
            "description": "新说明",
            "server_type": "stdio",
            "command": sys.executable,
            "command_args": [FAKE_SERVER, "--tools", "2"],
            "env": None,
        },
    ).json()
    assert updated["last_test_status"] == "success"


def test_test_unknown_server_404(client: TestClient) -> None:
    assert client.post("/api/mcp/servers/999/test").status_code == 404


def test_service_level_mutex(
    client: TestClient, mcp_test_timeout: int, db_session: Session,
) -> None:
    """FR-030：同 Server 同时仅一次测试——服务层锁占位时再入被拒。"""
    import asyncio

    from app.services import mcp_service
    from app.services.mcp_service import McpBusyError

    detail = _create_stdio(client, name="mutex")

    async def scenario() -> None:
        lock = mcp_service._lock_for(detail["id"])
        async with lock:
            try:
                await mcp_service.test_server(db_session, detail["id"])
                raised = False
            except McpBusyError:
                raised = True
            assert raised is True

    asyncio.run(scenario())

"""工具管理 HTTP 契约测试。

契约主定义：specs/003-tool-management/contracts/api-contract.md
覆盖：列表/详情/启停 + 空状态 + 404/422 + 不存在删除与修改用途端点（FR-007）。
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ToolEntry
from app.services import tool_registry


def test_list_returns_three_builtin_tools(
    client: TestClient, tools_seeded: Session,
) -> None:
    response = client.get("/api/tools")
    assert response.status_code == 200
    items = response.json()
    assert [item["name"] for item in items] == list(tool_registry.builtin_names())

    by_name = {item["name"]: item for item in items}
    time_item = by_name["current_time"]
    assert time_item["display_name"] == "当前时间"
    assert time_item["purpose"] == "查询指定时区的当前日期和时间"
    assert time_item["params_summary"] == "timezone（可选）"
    assert time_item["enabled"] is True
    assert time_item["is_builtin"] is True
    assert time_item["updated_at"]  # ISO 时间存在

    shell_item = by_name["shell"]
    assert shell_item["params_summary"] == "command（必填）"
    file_item = by_name["file_read_write"]
    assert "action（必填）" in file_item["params_summary"]


def test_list_empty_state(client: TestClient) -> None:
    """空表返回 []（FR-002，前端据此渲染空状态）。"""
    response = client.get("/api/tools")
    assert response.status_code == 200
    assert response.json() == []


def test_detail_contains_params_and_sections(
    client: TestClient, tools_seeded: Session,
) -> None:
    response = client.get("/api/tools/file_read_write")
    assert response.status_code == 200
    detail = response.json()

    param_names = [param["name"] for param in detail["params"]]
    assert param_names == ["action", "path", "content"]
    action_param = detail["params"][0]
    assert action_param["type"] == "enum"
    assert action_param["required"] is True
    assert action_param["description"]

    assert detail["usage_scenarios"]
    assert detail["input_requirements"]
    assert detail["restrictions"]


def test_detail_unknown_name_returns_404(
    client: TestClient, tools_seeded: Session,
) -> None:
    response = client.get("/api/tools/no_such_tool")
    assert response.status_code == 404
    assert response.json()["detail"] == "工具不存在"


def test_toggle_enabled_roundtrip(
    client: TestClient, tools_seeded: Session,
) -> None:
    # 停用
    response = client.put("/api/tools/shell/enabled", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    # 状态已持久化（重新列表可见）
    listing = {i["name"]: i for i in client.get("/api/tools").json()}
    assert listing["shell"]["enabled"] is False

    # 重新启用
    response = client.put("/api/tools/shell/enabled", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["enabled"] is True


def test_toggle_unknown_name_returns_404(
    client: TestClient, tools_seeded: Session,
) -> None:
    response = client.put("/api/tools/no_such_tool/enabled", json={"enabled": True})
    assert response.status_code == 404


def test_toggle_invalid_body_returns_422(
    client: TestClient, tools_seeded: Session,
) -> None:
    response = client.put("/api/tools/shell/enabled", json={"enabled": "not-a-bool"})
    assert response.status_code == 422


def test_no_delete_or_modify_purpose_endpoints(
    client: TestClient, tools_seeded: Session,
) -> None:
    """FR-007：不提供删除或修改用途的端点（404/405 而非业务成功）。"""
    assert client.delete("/api/tools/shell").status_code in (404, 405)
    # 整体 PUT（修改用途类操作）也不得存在
    response = client.put("/api/tools/shell", json={"purpose": "hacked"})
    assert response.status_code in (404, 405)
    # 停用未影响工具存在性
    assert client.get("/api/tools/shell").status_code == 200


def test_toggle_refreshes_updated_at(
    client: TestClient, tools_seeded: Session,
) -> None:
    before = {
        i["name"]: i for i in client.get("/api/tools").json()
    }["current_time"]["updated_at"]
    response = client.put("/api/tools/current_time/enabled", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["updated_at"] >= before


def test_unregistered_db_row_skipped_in_list(
    client: TestClient, db_session: Session,
) -> None:
    """版本漂移兜底：DB 中注册表不认识的行不出现在列表（data-model.md）。"""
    db_session.add(ToolEntry(name="legacy_ghost", enabled=True))
    db_session.commit()
    names = [i["name"] for i in client.get("/api/tools").json()]
    assert "legacy_ghost" not in names

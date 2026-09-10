"""契约测试：模型管理 7 个接口。

契约主定义：specs/002-model-management/contracts/api-contract.md
"""

from typing import Any

import httpx
import pytest

from app.services.openai_client import BadResponseFormatError, ChatHttpError, ChatReply


def make_payload(**overrides: Any) -> dict[str, Any]:
    """合法提交体（可覆盖字段）。"""
    payload: dict[str, Any] = {
        "display_name": "测试模型",
        "model_identifier": "gpt-test",
        "base_url": "https://api.example.com/v1",
        "api_key": None,
        "context_length": 8192,
        "max_output_tokens": 4096,
        "temperature": 0.7,
        "input_price": None,
        "output_price": None,
        "cached_input_price": None,
    }
    payload.update(overrides)
    return payload


# ---- 列表与空状态（US1 / FR-001/002）----


def test_list_empty_returns_empty_array(client: Any) -> None:
    assert client.get("/api/models").json() == []


def test_create_first_model_becomes_default(client: Any) -> None:
    resp = client.post("/api/models", json=make_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_default"] is True
    assert body["api_key_configured"] is False


def test_create_second_model_not_default(client: Any) -> None:
    client.post("/api/models", json=make_payload(display_name="A"))
    body = client.post("/api/models", json=make_payload(display_name="B")).json()
    assert body["is_default"] is False


# ---- 校验（US2 / FR-007/008）----


@pytest.mark.parametrize(
    "overrides",
    [
        {"display_name": " "},  # 空白视为未填（str_strip_whitespace 后为空）
        {"base_url": "ftp://example.com/v1"},
        {"base_url": "https://api.example.com/v1/chat/completions"},  # 误填完整路径
        {"context_length": 0},
        {"max_output_tokens": 99999, "context_length": 8192},  # 输出 > 上下文
        {"temperature": 2.5},
        {"input_price": -1},
    ],
)
def test_create_invalid_payload_returns_422(client: Any, overrides: dict[str, Any]) -> None:
    resp = client.post("/api/models", json=make_payload(**overrides))
    assert resp.status_code == 422
    assert "sk-" not in resp.text  # 错误信息不含密钥


def test_price_zero_vs_null_distinct(client: Any) -> None:
    """未配置（null）与免费（0）语义不同，详情需如实区分。"""
    free = client.post(
        "/api/models", json=make_payload(display_name="free", input_price=0),
    ).json()
    unknown = client.post(
        "/api/models", json=make_payload(display_name="unknown"),
    ).json()
    assert free["input_price"] == 0
    assert unknown["input_price"] is None


# ---- 密钥保护（US3 / FR-009~012）----


def test_responses_never_contain_api_key_plaintext(
    client: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-live-abcdef123456"

    def fake_send(base_url: str, identifier: str, api_key: str | None) -> ChatReply:
        raise ChatHttpError(500, "server error")

    monkeypatch.setattr(
        "app.services.model_service.openai_client.send_test_message", fake_send,
    )
    created = client.post("/api/models", json=make_payload(api_key=secret)).json()
    model_id = created["id"]

    snapshots = [
        client.get("/api/models").text,
        client.get(f"/api/models/{model_id}").text,
        client.post(f"/api/models/{model_id}/test-connection").text,
    ]
    for text in snapshots:
        assert secret not in text
    assert created["api_key_configured"] is True


def test_update_without_key_keeps_original(client: Any) -> None:
    created = client.post(
        "/api/models", json=make_payload(api_key="sk-keep-me"),
    ).json()
    model_id = created["id"]

    updated = client.put(
        f"/api/models/{model_id}", json=make_payload(display_name="改名"),
    ).json()
    assert updated["api_key_configured"] is True  # 留空保留原密钥


def test_update_with_new_key_replaces(client: Any) -> None:
    model_id = client.post(
        "/api/models", json=make_payload(api_key="sk-old"),
    ).json()["id"]
    updated = client.put(
        f"/api/models/{model_id}", json=make_payload(api_key="sk-new"),
    ).json()
    assert updated["api_key_configured"] is True


# ---- 详情与 404 ----


def test_get_unknown_model_returns_404(client: Any) -> None:
    assert client.get("/api/models/999").status_code == 404
    assert client.put("/api/models/999", json=make_payload()).status_code == 404
    assert client.delete("/api/models/999").status_code == 404


def test_get_detail_returns_editable_fields(client: Any) -> None:
    model_id = client.post(
        "/api/models",
        json=make_payload(temperature=0.3, input_price=1.5, output_price=2.5),
    ).json()["id"]
    detail = client.get(f"/api/models/{model_id}").json()
    assert detail["max_output_tokens"] == 4096
    assert detail["temperature"] == 0.3
    assert detail["input_price"] == 1.5
    assert detail["updated_at"]


# ---- 默认模型与删除（US4 / FR-017~021）----


def create_pair(client: Any) -> tuple[int, int]:
    """建两个模型，返回 (默认 id, 普通 id)。"""
    first = client.post("/api/models", json=make_payload(display_name="A")).json()
    second = client.post("/api/models", json=make_payload(display_name="B")).json()
    return first["id"], second["id"]


def test_set_default_switches_exclusively(client: Any) -> None:
    first_id, second_id = create_pair(client)
    resp = client.post(f"/api/models/{second_id}/default")
    assert resp.status_code == 200
    assert resp.json() == {"id": second_id, "is_default": True}
    defaults = [m for m in client.get("/api/models").json() if m["is_default"]]
    assert [m["id"] for m in defaults] == [second_id]


def test_delete_default_without_successor_choice_rejected(client: Any) -> None:
    first_id, second_id = create_pair(client)
    resp = client.delete(f"/api/models/{first_id}")  # 默认 + 还有其他模型
    assert resp.status_code == 400
    assert "默认" in resp.json()["detail"]


def test_delete_default_with_successor(client: Any) -> None:
    first_id, second_id = create_pair(client)
    resp = client.delete(f"/api/models/{first_id}?new_default_id={second_id}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}
    remaining = client.get("/api/models").json()
    assert [m["id"] for m in remaining] == [second_id]
    assert remaining[0]["is_default"] is True


def test_delete_last_model_clears_default(client: Any) -> None:
    model_id = client.post("/api/models", json=make_payload()).json()["id"]
    assert client.delete(f"/api/models/{model_id}").status_code == 200
    assert client.get("/api/models").json() == []
    # 删空后再新增会重新自动设默认（FR-018 到达路径）
    reborn = client.post("/api/models", json=make_payload()).json()
    assert reborn["is_default"] is True


# ---- 测试连接（US5 / FR-013~016）----


def _with_model(client: Any, api_key: str | None = "sk-test") -> int:
    return client.post("/api/models", json=make_payload(api_key=api_key)).json()["id"]


def test_connection_success(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_send(base_url: str, identifier: str, api_key: str | None) -> ChatReply:
        return ChatReply(content="你好，连接成功！")

    monkeypatch.setattr(
        "app.services.model_service.openai_client.send_test_message", fake_send,
    )
    model_id = _with_model(client)
    body = client.post(f"/api/models/{model_id}/test-connection").json()
    assert body["success"] is True
    assert body["category"] is None
    assert body["reply_excerpt"] == "你好，连接成功！"


@pytest.mark.parametrize(
    ("raised", "category"),
    [
        (ChatHttpError(401, "unauthorized"), "auth_error"),
        (ChatHttpError(403, "forbidden"), "auth_error"),
        (ChatHttpError(404, '{"error":{"message":"The model `x` does not exist"}}'), "model_not_found"),
        (ChatHttpError(502, "bad gateway"), "unreachable"),
        (httpx.ConnectError("refused"), "unreachable"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (BadResponseFormatError(), "bad_response"),
        (RuntimeError("weird"), "unknown"),
    ],
)
def test_connection_error_categories(
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
    raised: Exception,
    category: str,
) -> None:
    def fake_send(base_url: str, identifier: str, api_key: str | None) -> ChatReply:
        raise raised

    monkeypatch.setattr(
        "app.services.model_service.openai_client.send_test_message", fake_send,
    )
    model_id = _with_model(client, api_key="sk-leak-check")
    body = client.post(f"/api/models/{model_id}/test-connection").json()
    assert body["success"] is False
    assert body["category"] == category
    assert body["message"]
    assert "sk-leak-check" not in body["message"]  # FR-011


def test_connection_without_key_reports_auth_error(
    client: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str | None] = []

    def fake_send(base_url: str, identifier: str, api_key: str | None) -> ChatReply:
        calls.append(api_key)
        raise ChatHttpError(401, "no key")

    monkeypatch.setattr(
        "app.services.model_service.openai_client.send_test_message", fake_send,
    )
    model_id = _with_model(client, api_key=None)
    body = client.post(f"/api/models/{model_id}/test-connection").json()
    assert body["success"] is False
    assert calls == [None]  # 无密钥时以空密钥发起，由服务端 401 归类

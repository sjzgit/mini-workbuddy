"""Agent 管理 API 契约测试（specs/007-agent-management/contracts/agents-api.md）。

覆盖：列表/详情/新建/编辑/删除/设默认/binding-options、版本规则（FR-018~020）、
默认一致性（FR-021~25）、停用绑定保持（US5）、保存校验（422 分支）。
"""

import pytest


def _payload(
    name: str = "写作助手",
    model_id: int | None = 1,
    bindings: list[dict] | None = None,
    **overrides: object,
) -> dict:
    data: dict = {
        "name": name,
        "description": "用于写作的 Agent",
        "model_id": model_id,
        "system_prompt": "你是写作助手",
    }
    if bindings is not None:
        data["bindings"] = bindings  # None = 缺省（保持原绑定），[] = 显式清空
    data.update(overrides)
    return data


def _bind(resource_type: str, resource_id: int) -> dict:
    return {"resource_type": resource_type, "resource_id": resource_id}


def _create(client, model_id: int | None, **overrides) -> dict:
    response = client.post("/api/agents", json=_payload(model_id=model_id, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _detail(client, agent_id: int) -> dict:
    response = client.get(f"/api/agents/{agent_id}")
    assert response.status_code == 200, response.text
    return response.json()


class TestListAndCreate:
    def test_empty_list(self, client):
        response = client.get("/api/agents")
        assert response.status_code == 200
        assert response.json() == []

    def test_name_conflict_on_create(self, client, seed_model):
        _create(client, seed_model.id, name="A")
        response = client.post("/api/agents", json=_payload(name="A", model_id=seed_model.id))
        assert response.status_code == 409
        assert "同名" in response.json()["detail"]

    def test_name_conflict_on_edit_with_other(self, client, seed_model):
        _create(client, seed_model.id, name="A")
        b = _create(client, seed_model.id, name="B")
        response = client.put(
            f"/api/agents/{b['id']}", json=_payload(name="A", model_id=seed_model.id),
        )
        assert response.status_code == 409

    def test_edit_with_same_name_self_allowed(self, client, seed_model):
        created = _create(client, seed_model.id, name="A")
        response = client.put(
            f"/api/agents/{created['id']}", json=_payload(name="A", model_id=seed_model.id),
        )
        assert response.status_code == 200, response.text

    def test_list_default_first_then_recency(self, client, seed_model):
        a = _create(client, seed_model.id, name="A")
        b = _create(client, seed_model.id, name="B")
        # 设 B 为默认 → 默认置顶，A 在后
        response = client.post(f"/api/agents/{b['id']}/default")
        assert response.status_code == 200
        items = client.get("/api/agents").json()
        assert items[0]["id"] == b["id"]
        assert items[1]["id"] == a["id"]

    def test_create_second_not_default(self, client, seed_model):
        _create(client, seed_model.id, name="A")
        b = _create(client, seed_model.id, name="B")
        assert b["is_default"] is False

    def test_list_shape(self, client, seed_model, seed_resources):
        created = _create(
            client, seed_model.id,
            bindings=[_bind("tool", seed_resources["tools"][0].id)],
        )
        items = client.get("/api/agents").json()
        assert len(items) == 1
        item = items[0]
        assert item["id"] == created["id"]
        assert item["name"] == "写作助手"
        entries_marker = None  # 结构核对：模型名/标识与计数
        assert item["model_display_name"] == "GPT 测试模型"
        assert item["model_identifier"] == "gpt-test"
        assert item["tool_count"] == 1
        assert item["skill_count"] == 0
        assert item["mcp_count"] == 0
        assert item["bindings"][0]["name"] == seed_resources["tools"][0].name
        assert item["is_default"] is True
        assert "updated_at" in item

    def test_list_bindings_full_not_truncated(self, client, seed_model, seed_resources):
        tools = seed_resources["tools"]
        bindings = [_bind("tool", t.id) for t in tools[:3]]
        skill = seed_resources["skills"]["on"]
        created = _create(client, seed_model.id, bindings=bindings)
        response = client.put(
            f"/api/agents/{created['id']}",
            json=_payload(model_id=seed_model.id, bindings=[*bindings, _bind("skill", skill.id)]),
        )
        assert response.status_code == 200, response.text
        items = client.get("/api/agents").json()
        assert len(items[0]["bindings"]) == 4  # 全量返回，不做 top3 截断
        assert [b["resource_type"] for b in items[0]["bindings"]] == ["tool"] * 3 + ["skill"]

    def test_binding_nonexistent_resource_422(self, client, seed_model):
        response = client.post(
            "/api/agents",
            json=_payload(model_id=seed_model.id, bindings=[_bind("mcp", 9999)]),
        )
        assert response.status_code == 422
        assert "不存在" in response.json()["detail"]

    def test_edit_nonexistent_agent_404(self, client, seed_model):
        response = client.put(
            "/api/agents/9999",
            json=_payload(model_id=seed_model.id),
        )
        assert response.status_code == 404

    def test_detail_404(self, client, seed_model):
        _create(client, seed_model.id, name="A")
        assert client.get("/api/agents/9999").status_code == 404


class TestBindingOptions:
    def test_only_enabled_options(self, client, seed_model, seed_resources):
        body = client.get("/api/agents/binding-options").json()
        assert [o["id"] for o in body["tools"]] == [t.id for t in seed_resources["tools"]]
        skill_ids = [o["id"] for o in body["skills"]]
        assert seed_resources["skills"]["on"].id in skill_ids
        assert seed_resources["skills"]["off"].id not in skill_ids
        mcp_ids = [o["id"] for o in body["mcp_servers"]]
        assert seed_resources["mcps"]["on"].id in mcp_ids
        assert seed_resources["mcps"]["off"].id not in mcp_ids
        assert body["models"][0]["display_name"] == "GPT 测试模型"
        assert body["models"][0]["model_identifier"] == "gpt-test"
        assert body["models"][0]["is_default"] is True
        assert body["prompt_template"].startswith("# 角色：")

    def test_selected_echo(self, client, seed_model, seed_resources):
        created = _create(
            client, seed_model.id,
            bindings=[_bind("tool", seed_resources["tools"][0].id)],
        )
        body = client.get(f"/api/agents/binding-options?agent_id={created['id']}").json()
        by_id = {o["id"]: o for o in body["tools"]}
        assert by_id[seed_resources["tools"][0].id]["selected"] is True
        assert by_id[seed_resources["tools"][1].id]["selected"] is False

    def test_no_models_empty_list(self, client):
        body = client.get("/api/agents/binding-options").json()
        assert body["models"] == []
        assert body["prompt_template"].startswith("# 角色：")


class TestValidation:
    def test_name_required(self, client, seed_model):
        response = client.post("/api/agents", json=_payload(name="   ", model_id=seed_model.id))
        assert response.status_code == 422
        assert "名称" in response.json()["detail"]

    def test_model_required(self, client):
        response = client.post("/api/agents", json=_payload(model_id=9999))
        assert response.status_code == 422
        assert "模型" in response.json()["detail"]

    def test_model_missing_field(self, client):
        response = client.post("/api/agents", json=_payload(model_id=None))
        assert response.status_code == 422

    def test_max_rounds_zero(self, client, seed_model):
        response = client.post("/api/agents", json=_payload(max_rounds=0, model_id=seed_model.id))
        assert response.status_code == 422

    def test_max_rounds_negative(self, client, seed_model):
        response = client.post(
            "/api/agents", json=_payload(max_rounds=-3, model_id=seed_model.id),
        )
        assert response.status_code == 422

    def test_max_rounds_over_100(self, client, seed_model):
        response = client.post(
            "/api/agents", json=_payload(max_rounds=101, model_id=seed_model.id),
        )
        assert response.status_code == 422

    def test_thinking_level_invalid(self, client, seed_model):
        response = client.post(
            "/api/agents",
            json=_payload(model_id=seed_model.id, thinking_level="ultra"),
        )
        assert response.status_code == 422

    def test_thinking_fields_roundtrip(self, client, seed_model):
        created = _create(
            client, seed_model.id,
            enable_deep_thinking=True, thinking_level="high",
        )
        assert created["enable_deep_thinking"] is True
        assert created["thinking_level"] == "high"
        # 编辑改回
        response = client.put(
            f"/api/agents/{created['id']}",
            json=_payload(
                model_id=seed_model.id,
                enable_deep_thinking=False, thinking_level="low",
            ),
        )
        assert response.status_code == 200, response.text
        assert response.json()["enable_deep_thinking"] is False
        assert response.json()["thinking_level"] == "low"

    def test_invalid_resource_type(self, client, seed_model):
        response = client.post(
            "/api/agents",
            json=_payload(
                model_id=seed_model.id,
                bindings=[{"resource_type": "mcpx", "resource_id": 1}],
            ),
        )
        assert response.status_code == 422

    def test_duplicate_binding(self, client, seed_model, seed_resources):
        tool_id = seed_resources["tools"][0].id
        response = client.post(
            "/api/agents",
            json=_payload(
                model_id=seed_model.id,
                bindings=[_bind("tool", tool_id), _bind("tool", tool_id)],
            ),
        )
        assert response.status_code == 422


class TestPromptVersions:
    def test_edit_name_only_keeps_version(self, client, seed_model):
        created = _create(client, seed_model.id, name="A")
        response = client.put(
            f"/api/agents/{created['id']}",
            json=_payload(model_id=seed_model.id, name="A2"),
        )
        assert response.status_code == 200, response.text
        assert len(response.json()["prompt_versions"]) == 1

    def test_edit_prompt_bumps_version(self, client, seed_model):
        created = _create(client, seed_model.id)
        response = client.put(
            f"/api/agents/{created['id']}",
            json=_payload(model_id=seed_model.id, system_prompt="v2 内容"),
        )
        assert response.status_code == 200, response.text
        versions = response.json()["prompt_versions"]
        assert len(versions) == 2
        assert versions[-1]["version"] == 2
        assert versions[-1]["content"] == "v2 内容"

    def test_edit_same_prompt_no_bump(self, client, seed_model):
        created = _create(client, seed_model.id, system_prompt="固定内容")
        response = client.put(
            f"/api/agents/{created['id']}",
            json=_payload(model_id=seed_model.id, system_prompt="固定内容", name="改名"),
        )
        assert response.status_code == 200, response.text
        assert len(response.json()["prompt_versions"]) == 1

    def test_edit_from_history_creates_new_version(self, client, seed_model):
        created = _create(client, seed_model.id, system_prompt="v1")
        client.put(
            f"/api/agents/{created['id']}",
            json=_payload(model_id=seed_model.id, system_prompt="v2"),
        )
        response = client.put(
            f"/api/agents/{created['id']}",
            json=_payload(model_id=seed_model.id, system_prompt="v1"),
        )
        assert response.status_code == 200, response.text
        versions = response.json()["prompt_versions"]
        assert [v["version"] for v in versions] == [1, 2, 3]
        assert versions[-1]["content"] == "v1"
        assert versions[0]["content"] == "v1"
        assert versions[1]["content"] == "v2"


class TestDeleteAndDefault:
    def test_delete_normal(self, client, seed_model):
        a = _create(client, seed_model.id, name="A")
        b = _create(client, seed_model.id, name="B")
        response = client.delete(f"/api/agents/{b['id']}")
        assert response.status_code == 200
        assert response.json()["cleared_default"] is False
        items = client.get("/api/agents").json()
        assert [i["id"] for i in items] == [a["id"]]

    def test_delete_default_without_new_default_409(self, client, seed_model):
        a = _create(client, seed_model.id, name="A")
        _create(client, seed_model.id, name="B")
        response = client.delete(f"/api/agents/{a['id']}")
        assert response.status_code == 409
        body = response.json()["detail"]
        assert body["requires_new_default"] is True
        assert [c["name"] for c in body["candidates"]] == ["B"]

    def test_delete_default_with_successor(self, client, seed_model):
        a = _create(client, seed_model.id, name="A")
        b = _create(client, seed_model.id, name="B")
        response = client.delete(f"/api/agents/{a['id']}?new_default_id={b['id']}")
        assert response.status_code == 200, response.text
        items = client.get("/api/agents").json()
        assert [i["id"] for i in items] == [b["id"]]
        assert items[0]["is_default"] is True

    def test_delete_default_bad_successor_400(self, client, seed_model):
        a = _create(client, seed_model.id, name="A")
        _create(client, seed_model.id, name="B")
        response = client.delete(f"/api/agents/{a['id']}?new_default_id=9999")
        assert response.status_code == 400

    def test_delete_last_clears_default(self, client, seed_model):
        a = _create(client, seed_model.id, name="A")
        response = client.delete(f"/api/agents/{a['id']}")
        assert response.status_code == 200
        assert response.json()["cleared_default"] is True
        assert client.get("/api/agents").json() == []

    def test_set_default_switch_and_idempotent(self, client, seed_model):
        a = _create(client, seed_model.id, name="A")
        b = _create(client, seed_model.id, name="B")
        response = client.post(f"/api/agents/{b['id']}/default")
        assert response.status_code == 200
        items = {i["id"]: i for i in client.get("/api/agents").json()}
        assert items[b["id"]]["is_default"] is True
        assert items[a["id"]]["is_default"] is False
        response = client.post(f"/api/agents/{b['id']}/default")
        assert response.status_code == 200
        items = {i["id"]: i for i in client.get("/api/agents").json()}
        assert items[b["id"]]["is_default"] is True

    def test_delete_invalid_id_404(self, client, seed_model):
        _create(client, seed_model.id, name="A")
        assert client.delete("/api/agents/9999").status_code == 404

    def test_set_default_invalid_id_404(self, client, seed_model):
        _create(client, seed_model.id, name="A")
        assert client.post("/api/agents/9999/default").status_code == 404


class TestDisabledBinding:
    def test_disabled_binding_kept_and_marked(self, client, seed_model, seed_resources):
        skill_on = seed_resources["skills"]["on"]
        skill_off = seed_resources["skills"]["off"]
        created = _create(
            client, seed_model.id,
            bindings=[_bind("skill", skill_on.id), _bind("skill", skill_off.id)],
        )
        detail = _detail(client, created["id"])
        by_key = {(b["resource_type"], b["resource_id"]): b for b in detail["bindings"]}
        assert by_key[("skill", skill_on.id)]["enabled"] is True
        assert by_key[("skill", skill_off.id)]["enabled"] is False
        items = client.get("/api/agents").json()
        assert items[0]["skill_count"] == 2

    def test_save_keeps_disabled_binding(self, client, seed_model, seed_resources):
        skill_off = seed_resources["skills"]["off"]
        created = _create(client, seed_model.id, bindings=[_bind("skill", skill_off.id)])
        response = client.put(
            f"/api/agents/{created['id']}",
            json=_payload(model_id=seed_model.id, name="改名保存"),
        )
        assert response.status_code == 200, response.text
        detail = _detail(client, created["id"])
        assert len(detail["bindings"]) == 1
        assert detail["bindings"][0]["enabled"] is False

    def test_save_can_remove_disabled_binding(self, client, seed_model, seed_resources):
        skill_off = seed_resources["skills"]["off"]
        created = _create(client, seed_model.id, bindings=[_bind("skill", skill_off.id)])
        response = client.put(
            f"/api/agents/{created['id']}",
            json=_payload(model_id=seed_model.id, bindings=[]),
        )
        assert response.status_code == 200, response.text
        assert _detail(client, created["id"])["bindings"] == []


class TestCompactConfig:
    """011：Agent 压缩配置四字段（contracts/agent-compression-config.md）。"""

    def test_defaults_and_roundtrip(self, client, db_session, seed_model) -> None:
        payload = {
            "name": "压缩 Agent", "model_id": seed_model.id,
            "system_prompt": "", "max_rounds": 3,
        }
        resp = client.post("/api/agents", json=payload)
        assert resp.status_code == 201
        detail = client.get(f"/api/agents/{resp.json()['id']}").json()
        assert detail["auto_compact"] is True
        assert detail["compact_trigger_ratio"] == 0.8
        assert detail["compact_keep_recent_rounds"] == 5
        assert detail["compact_summary_target_tokens"] == 1000

    def test_save_and_reload(self, client, db_session, seed_model, seed_agent) -> None:
        body = {
            "name": seed_agent.name, "model_id": seed_model.id,
            "system_prompt": seed_agent.system_prompt,
            "max_rounds": 3,
            "auto_compact": False,
            "compact_trigger_ratio": 0.6,
            "compact_keep_recent_rounds": 3,
            "compact_summary_target_tokens": 500,
        }
        resp = client.put(f"/api/agents/{seed_agent.id}", json=body)
        assert resp.status_code in (200, 201)
        detail = client.get(f"/api/agents/{seed_agent.id}").json()
        assert detail["auto_compact"] is False
        assert detail["compact_trigger_ratio"] == 0.6
        assert detail["compact_keep_recent_rounds"] == 3
        assert detail["compact_summary_target_tokens"] == 500

    @pytest.mark.parametrize("field,value", [
        ("compact_trigger_ratio", 0.3),
        ("compact_trigger_ratio", 0.99),
        ("compact_keep_recent_rounds", 0),
        ("compact_keep_recent_rounds", 99),
        ("compact_summary_target_tokens", 50),
        ("compact_summary_target_tokens", 9999),
    ])
    def test_invalid_values_422(self, client, db_session, seed_model, seed_agent, field, value) -> None:
        body = {
            "name": seed_agent.name, "model_id": seed_model.id,
            "system_prompt": seed_agent.system_prompt,
            "max_rounds": 3, field: value,
        }
        resp = client.put(f"/api/agents/{seed_agent.id}", json=body)
        assert resp.status_code == 422

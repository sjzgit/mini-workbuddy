"""Agent 引用保护测试（US6，specs/007-agent-management/contracts/agents-api.md 引用保护节）。"""

import pytest


@pytest.fixture
def agent_with_refs(client, seed_model, seed_resources):
    """一个引用了模型、工具、Skill、MCP 的 Agent。"""
    response = client.post("/api/agents", json={
        "name": "引用者",
        "model_id": seed_model.id,
        "system_prompt": "p",
        "bindings": [
            {"resource_type": "tool", "resource_id": seed_resources["tools"][0].id},
            {"resource_type": "skill", "resource_id": seed_resources["skills"]["on"].id},
            {"resource_type": "mcp", "resource_id": seed_resources["mcps"]["on"].id},
        ],
    })
    assert response.status_code == 201
    return {
        "agent": response.json(),
        "tools": seed_resources["tools"],
        "skills": seed_resources["skills"],
        "mcps": seed_resources["mcps"],
    }


class TestDeleteProtection:
    def test_model_delete_blocked(self, client, seed_model, agent_with_refs):
        response = client.delete(f"/api/models/{seed_model.id}")
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "引用者" in detail["detail"]
        assert detail["referenced_by_agents"] == [
            {"id": agent_with_refs["agent"]["id"], "name": "引用者"},
        ]

    def test_skill_delete_blocked(self, client, agent_with_refs):
        skill = agent_with_refs["skills"]["on"]
        response = client.delete(f"/api/skills/{skill.dir_name}")
        assert response.status_code == 409
        assert "引用者" in response.json()["detail"]["detail"]

    def test_mcp_delete_blocked(self, client, agent_with_refs):
        mcp = agent_with_refs["mcps"]["on"]
        response = client.delete(f"/api/mcp/servers/{mcp.id}")
        assert response.status_code == 409
        assert "引用者" in response.json()["detail"]["detail"]

    def test_unreferenced_resource_404_untouched(self, client, agent_with_refs):
        assert client.delete("/api/models/9999").status_code == 404

    def test_remove_binding_then_deletable(self, client, seed_model, agent_with_refs):
        skill = agent_with_refs["skills"]["on"]
        client.put(
            f"/api/agents/{agent_with_refs['agent']['id']}",
            json={"name": "引用者", "model_id": seed_model.id, "system_prompt": "p", "bindings": []},
        )
        assert client.delete(f"/api/skills/{skill.dir_name}").status_code == 200

    def test_delete_agent_then_deletable(self, client, agent_with_refs):
        mcp = agent_with_refs["mcps"]["on"]
        agent_id = agent_with_refs["agent"]["id"]
        assert client.delete(f"/api/agents/{agent_id}").status_code == 200
        assert client.delete(f"/api/mcp/servers/{mcp.id}").status_code == 200

    def test_default_model_checked_before_default_switch(self, client, seed_model, agent_with_refs):
        second = client.post("/api/models", json={
            "display_name": "备用模型",
            "model_identifier": "backup",
            "base_url": "https://backup.example.com/v1",
            "context_length": 4096,
            "max_output_tokens": 2048,
            "temperature": 0.5,
        })
        assert second.status_code == 201
        response = client.delete(f"/api/models/{seed_model.id}?new_default_id={second.json()['id']}")
        assert response.status_code == 409
        models = client.get("/api/models").json()
        still_default = [m for m in models if m["id"] == seed_model.id][0]
        assert still_default["is_default"] is True

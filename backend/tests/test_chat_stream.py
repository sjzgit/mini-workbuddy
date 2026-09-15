"""聊天流式与生成控制测试（specs/008-chat-conversations）。

T016/T032/T036/T039：SSE 事件序列、上下文构造、停止、孤儿恢复、异常分类。
真实模型交互不在测试范围（research R9 假流注入）。
"""

import json
import time

import pytest
from app.models import MessageEntry
from app.services.generation_registry import get_registry
from app.services.openai_client import ChatHttpError, ContentDelta, ReasoningDelta
from fastapi.testclient import TestClient

from tests.conftest import BLOCK, FakeStream


def wait_terminal(message_id: int, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = get_registry().get(message_id)
        if task is None or task.terminal_event is not None:
            return
        time.sleep(0.01)
    raise AssertionError(f"generation #{message_id} did not finish in {timeout}s")


def read_sse(client: TestClient, conversation_id: int, message_id: int) -> list[tuple[str, dict]]:
    """同步读取 SSE 流直至流关闭，返回 (event, data) 列表。"""
    events: list[tuple[str, dict]] = []
    with client.stream(
        "GET", f"/api/conversations/{conversation_id}/messages/{message_id}/stream",
    ) as response:
        assert response.status_code == 200
        current_event: str | None = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                current_event = line[len("event: "):]
            elif line.startswith("data: ") and current_event is not None:
                events.append((current_event, json.loads(line[len("data: "):])))
                current_event = None
    return events


@pytest.fixture
def stream_env(
    client: TestClient,
    seed_conversation,
    fake_stream: FakeStream,
    chat_session_factory,
    clean_registry,
):
    return {
        "client": client,
        "conversation": seed_conversation,
        "fake": fake_stream,
    }


def _send(client: TestClient, cid: int, content: str):
    return client.post(f"/api/conversations/{cid}/messages", json={"content": content})


class TestStreamEvents:
    def test_replay_and_live_deltas(self, stream_env) -> None:
        env = stream_env
        env["fake"].script(ContentDelta(text="回答正文"))
        response = _send(env["client"], env["conversation"].id, "你好")
        assert response.status_code == 201
        reply_id = response.json()["reply_message_id"]
        wait_terminal(reply_id)
        # 晚订阅：重放缓冲获得全部增量 + done
        events = read_sse(env["client"], env["conversation"].id, reply_id)
        kinds = [event for event, _ in events]
        assert kinds == ["content_delta", "done"]
        done = events[-1][1]
        assert done["message"]["status"] == "completed"
        assert done["message"]["content"] == "回答正文"

    def test_reasoning_content_partition(self, stream_env) -> None:
        env = stream_env
        env["fake"].script(
            ReasoningDelta(text="先想一步 "),
            ReasoningDelta(text="再想两步"),
            ContentDelta(text="回答正文"),
        )
        response = _send(env["client"], env["conversation"].id, "问题")
        reply_id = response.json()["reply_message_id"]
        wait_terminal(reply_id)
        events = read_sse(env["client"], env["conversation"].id, reply_id)
        kinds = [event for event, _ in events]
        assert kinds == ["reasoning_delta", "reasoning_delta", "content_delta", "done"]
        done = events[-1][1]
        assert done["message"]["reasoning_content"] == "先想一步 再想两步"
        assert done["message"]["content"] == "回答正文"
        assert done["message"]["status"] == "completed"

    def test_error_then_done_incomplete(self, stream_env) -> None:
        env = stream_env
        env["fake"].script(
            ContentDelta(text="部分内容"),
            ChatHttpError(401, "invalid api key"),
        )
        response = _send(env["client"], env["conversation"].id, "问题")
        reply_id = response.json()["reply_message_id"]
        wait_terminal(reply_id)
        events = read_sse(env["client"], env["conversation"].id, reply_id)
        kinds = [event for event, _ in events]
        assert kinds == ["content_delta", "error", "done"]
        error = events[1][1]
        assert error["category"] == "auth_error"
        assert "认证失败" in error["message"]
        done = events[2][1]
        assert done["message"]["status"] == "incomplete"
        assert done["message"]["content"] == "部分内容"
        # 错误文本不入正文（FR-023）
        assert "认证失败" not in done["message"]["content"]

    def test_empty_response_deleted_row(self, stream_env) -> None:
        env = stream_env
        env["fake"].script()
        response = _send(env["client"], env["conversation"].id, "问题")
        reply_id = response.json()["reply_message_id"]
        wait_terminal(reply_id)
        # 无正文 → 占位行被删除（FR-024）：消息列表只剩用户消息
        messages = env["client"].get(f"/api/conversations/{env['conversation'].id}/messages")
        items = messages.json()
        assert [m["role"] for m in items] == ["user"]
        # 任务已从注册表移除
        assert get_registry().get(reply_id) is None

    def test_orphan_generating_marked_incomplete(self, stream_env) -> None:
        env = stream_env
        cid = env["conversation"].id
        env["fake"].script(BLOCK)  # 阻塞保持 generating 占位行存在
        response = _send(env["client"], cid, "问题")
        reply_id = response.json()["reply_message_id"]
        # 伪造进程重启：清空注册表后再订阅 → 孤儿路径
        get_registry()._tasks.clear()
        events = read_sse(env["client"], cid, reply_id)
        kinds = [event for event, _ in events]
        assert kinds == ["done"]
        assert events[0][1]["message"]["status"] == "incomplete"

    def test_regenerate_resets_in_place(self, stream_env) -> None:
        env = stream_env
        env["fake"].script(ContentDelta(text="第一版回答"))
        cid = env["conversation"].id
        response = _send(env["client"], cid, "问题")
        reply_id = response.json()["reply_message_id"]
        wait_terminal(reply_id)
        env["fake"].script(ContentDelta(text="第二版回答"))
        regen = env["client"].post(f"/api/conversations/{cid}/regenerate")
        assert regen.status_code == 201
        assert regen.json()["reply_message_id"] == reply_id  # 同一行原地重置
        wait_terminal(reply_id)
        events = read_sse(env["client"], cid, reply_id)
        done = events[-1][1]
        assert done["message"]["content"] == "第二版回答"
        assert done["message"]["seq"] == 2  # user(1) + reply(2)

    def test_regenerate_rejects_non_assistant_last(self, stream_env) -> None:
        env = stream_env
        cid = env["conversation"].id
        body = env["client"].post(f"/api/conversations/{cid}/regenerate")
        assert body.status_code == 409
        assert "仅最后一条" in body.json()["detail"]


class TestContextConstruction:
    def test_context_includes_valid_history_once(self, stream_env) -> None:
        env = stream_env
        cid = env["conversation"].id
        env["fake"].script(ContentDelta(text="第一次回答"))
        first = _send(env["client"], cid, "第一问")
        wait_terminal(first.json()["reply_message_id"])
        env["fake"].script(ContentDelta(text="第二次回答"))
        second = _send(env["client"], cid, "第二问")
        wait_terminal(second.json()["reply_message_id"])
        # 第二次请求：system + [user1, assistant1, user2]，本条消息仅一次（FR-016）
        messages = env["fake"].calls[-1]["messages"]
        roles = [m["role"] for m in messages]
        assert roles == ["system", "user", "assistant", "user"]
        assert messages[-1]["content"] == "第二问"
        assert sum(1 for m in messages if m["content"] == "第二问") == 1
        assert messages[0]["content"] == "你是一个测试助手。"

    def test_switch_agent_then_send_uses_new_prompt(self, stream_env) -> None:
        env = stream_env
        cid = env["conversation"].id
        env["fake"].script(ContentDelta(text="第一次回答"))
        wait_terminal(_send(env["client"], cid, "第一问").json()["reply_message_id"])
        # 新建 Agent B（用同一模型）并切换会话 Agent
        options = env["client"].get("/api/agents/binding-options").json()
        model_id = options["models"][0]["id"]
        created = env["client"].post(
            "/api/agents",
            json={"name": "文言助手", "model_id": model_id, "system_prompt": "用文言文回答。"},
        )
        assert created.status_code == 201, created.text
        agent_b = created.json()
        switched = env["client"].put(f"/api/conversations/{cid}", json={"agent_id": agent_b["id"]})
        assert switched.status_code == 200
        assert switched.json()["agent_id"] == agent_b["id"]
        # 切换后发送：system 应为 B 的提示词，回复归属快照为 B
        env["fake"].script(ContentDelta(text="第二次回答"))
        second = _send(env["client"], cid, "第二问")
        assert second.status_code == 201
        reply_id = second.json()["reply_message_id"]
        wait_terminal(reply_id)
        messages = env["fake"].calls[-1]["messages"]
        assert messages[0] == {"role": "system", "content": "用文言文回答。"}
        listing = env["client"].get(f"/api/conversations/{cid}/messages").json()
        reply = next(m for m in listing if m["id"] == reply_id)
        assert reply["agent_name"] == "文言助手"


class TestStopGeneration:
    def test_stop_blocking_generation(self, stream_env) -> None:
        env = stream_env
        cid = env["conversation"].id
        env["fake"].script(
            ContentDelta(text="开头"),
            BLOCK,
            ContentDelta(text="不该出现"),
        )
        response = _send(env["client"], cid, "问题")
        reply_id = response.json()["reply_message_id"]
        deadline = time.time() + 2
        while time.time() < deadline and env["fake"].unblocked:
            time.sleep(0.01)
        stop = env["client"].post(f"/api/conversations/{cid}/messages/{reply_id}/stop")
        assert stop.status_code == 200
        assert stop.json() == {"stopped": True}
        wait_terminal(reply_id)
        events = read_sse(env["client"], cid, reply_id)
        done = events[-1][1]
        assert done["stopped"] is True
        assert done["message"]["status"] == "incomplete"
        assert done["message"]["content"] == "开头"

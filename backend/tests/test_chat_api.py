"""聊天 REST 契约测试（specs/008-chat-conversations/contracts/chat-api.md）。

T015：会话创建/列表、消息发送的 HTTP 契约与错误映射。
流式行为见 test_chat_stream.py；真实模型交互不在测试范围（research R9）。
"""

import time

import pytest
from app.services.generation_registry import get_registry
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import BLOCK, FakeStream

# ---- helpers ----


def wait_terminal(message_id: int, timeout: float = 2.0) -> None:
    """等待生成任务进入终态（测试用轮询）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = get_registry().get(message_id)
        if task is None or task.terminal_event is not None:
            return
        time.sleep(0.01)
    raise AssertionError(f"generation #{message_id} did not finish in {timeout}s")


@pytest.fixture
def chat_env(
    client: TestClient,
    db_session: Session,
    seed_agent,
    seed_conversation,
    fake_stream: FakeStream,
    chat_session_factory,
    clean_registry,
):
    """聊天测试环境：一次备齐路由客户端 + 种子数据 + 假流。"""
    return {
        "client": client,
        "db": db_session,
        "agent": seed_agent,
        "conversation": seed_conversation,
        "fake": fake_stream,
    }


# ---- 会话创建与列表 ----


class TestConversationEndpoints:
    def test_create_conversation_201(self, chat_env) -> None:
        body = chat_env["client"].post(
            "/api/conversations", json={"agent_id": chat_env["agent"].id},
        )
        assert body.status_code == 201
        data = body.json()
        assert data["title"] == "新会话"
        assert data["agent_id"] == chat_env["agent"].id
        assert data["updated_at"] and data["created_at"]

    def test_create_conversation_agent_missing_400(self, chat_env) -> None:
        body = chat_env["client"].post("/api/conversations", json={"agent_id": 99999})
        assert body.status_code == 400

    def test_list_conversations_summary_desc(self, chat_env) -> None:
        client = chat_env["client"]
        client.post("/api/conversations", json={"agent_id": chat_env["agent"].id})
        body = client.get("/api/conversations")
        assert body.status_code == 200
        items = body.json()
        assert len(items) >= 1
        times = [item["updated_at"] for item in items]
        assert times == sorted(times, reverse=True)
        # 摘要不含消息字段（FR-006）
        assert "messages" not in items[0]


# ---- 发送消息契约 ----


class TestSendMessage:
    def test_send_message_201_structure(self, chat_env) -> None:
        chat_env["fake"].script()
        client = chat_env["client"]
        response = client.post(
            f"/api/conversations/{chat_env['conversation'].id}/messages",
            json={"content": "你好"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["user_message"]["content"] == "你好"
        assert data["user_message"]["role"] == "user"
        assert data["reply_message_id"] > data["user_message"]["id"]
        assert data["conversation"]["title"] == "你好"  # 标题截取（FR-007）
        wait_terminal(data["reply_message_id"])

    def test_send_empty_content_422(self, chat_env) -> None:
        for content in ("", "   "):
            response = chat_env["client"].post(
                f"/api/conversations/{chat_env['conversation'].id}/messages",
                json={"content": content},
            )
            assert response.status_code == 422

    def test_send_overlong_content_422(self, chat_env) -> None:
        response = chat_env["client"].post(
            f"/api/conversations/{chat_env['conversation'].id}/messages",
            json={"content": "字" * 32001},
        )
        assert response.status_code == 422

    def test_send_context_overflow_422(self, chat_env) -> None:
        # context_length=8192，max_output=4096；构造超过 (8192-4096)/0.6 字符的输入
        response = chat_env["client"].post(
            f"/api/conversations/{chat_env['conversation'].id}/messages",
            json={"content": "长" * 9000},
        )
        assert response.status_code == 422
        assert "上下文容量" in response.json()["detail"]

    def test_send_twice_while_generating_409(self, chat_env) -> None:
        chat_env["fake"].script(BLOCK)
        client = chat_env["client"]
        first = client.post(
            f"/api/conversations/{chat_env['conversation'].id}/messages",
            json={"content": "第一条"},
        )
        assert first.status_code == 201
        reply_id = first.json()["reply_message_id"]
        second = client.post(
            f"/api/conversations/{chat_env['conversation'].id}/messages",
            json={"content": "第二条"},
        )
        assert second.status_code == 409
        assert "正在生成" in second.json()["detail"]
        chat_env["fake"].unblocked = True
        wait_terminal(reply_id)

    def test_title_truncation_long_message(self, chat_env) -> None:
        chat_env["fake"].script()
        long_text = "这是一条非常长的消息内容用于验证标题截取规则是否生效" * 2
        response = chat_env["client"].post(
            f"/api/conversations/{chat_env['conversation'].id}/messages",
            json={"content": long_text},
        )
        title = response.json()["conversation"]["title"]
        assert len(title) == 21  # 20 字符 + 省略号
        assert title.endswith("…")
        wait_terminal(response.json()["reply_message_id"])

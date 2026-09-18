"""ask-answers 回答端点契约测试（specs/013-ask-user-tool，契约 §3）。

用内存注册表模拟"生成中 + 挂起询问"，覆盖 200/404/409/422 全部分支。
"""

import pytest

from app.models import MessageEntry
from app.services.agent_runtime import ask_user as ask_registry
from app.services.generation_registry import GenerationTask, get_registry


@pytest.fixture
def clean_state():
    """清空生成注册表与挂起注册表（用例隔离）。"""
    get_registry()._tasks.clear()
    ask_registry._registry.clear()
    yield
    get_registry()._tasks.clear()
    ask_registry._registry.clear()


@pytest.fixture
def generating_message(
    db_session, seed_conversation, seed_agent, clean_state,
) -> MessageEntry:
    """一条生成中的 assistant 占位消息 + 对应 GenerationTask（依赖 clean_state 先清理）。"""
    message = MessageEntry(
        conversation_id=seed_conversation.id,
        role="assistant",
        agent_id=seed_agent.id,
        agent_name=seed_agent.name,
        content="",
        status="generating",
        seq=1,
    )
    db_session.add(message)
    db_session.commit()
    task = GenerationTask(
        conversation_id=seed_conversation.id, reply_message_id=message.id,
    )
    get_registry().register(task)
    return message


def _ask_url(message: MessageEntry) -> str:
    return f"/api/conversations/{message.conversation_id}/messages/{message.id}/ask-answers"


def test_message_not_found_404(client, seed_conversation) -> None:
    response = client.post(
        f"/api/conversations/{seed_conversation.id}/messages/999999/ask-answers",
        json={"call_id": "call_x", "selected": ["方案A"]},
    )
    assert response.status_code == 404


def test_late_answer_409(client, generating_message, clean_state) -> None:
    """生成已终态（注册表无任务）→ 409。"""
    get_registry().remove(generating_message.id)  # 模拟任务已结束移除
    response = client.post(
        _ask_url(generating_message),
        json={"call_id": "call_x", "selected": ["方案A"]},
    )
    assert response.status_code == 409
    assert "生成已结束" in response.json()["detail"]


def test_empty_answer_422(client, generating_message, clean_state) -> None:
    """空回答（无选项且无文本）→ 422（FR-008 服务端兜底）。"""
    response = client.post(
        _ask_url(generating_message),
        json={"call_id": "call_x", "selected": [], "text": "   "},
    )
    assert response.status_code == 422
    assert "回答不能为空" in response.json()["detail"]


def test_call_id_miss_404(client, generating_message, clean_state) -> None:
    """生成中但 call_id 无对应挂起 → 404。"""
    response = client.post(
        _ask_url(generating_message),
        json={"call_id": "no_such_call", "selected": ["方案A"]},
    )
    assert response.status_code == 404
    assert "没有等待回答的询问" in response.json()["detail"]


def test_success_resolves_pending(client, generating_message, clean_state) -> None:
    """成功：答案写入挂起项并唤醒（200 resolved=true）。"""
    ask_registry.register("call_ok")
    response = client.post(
        _ask_url(generating_message),
        json={"call_id": "call_ok", "selected": ["方案A", "方案C"], "text": None},
    )
    assert response.status_code == 200
    assert response.json() == {"resolved": True}
    pending = ask_registry.get("call_ok")
    assert pending is not None
    assert pending.answered.is_set()
    assert pending.selected == ["方案A", "方案C"]


def test_multi_select_with_other_text(client, generating_message, clean_state) -> None:
    """选项 + 其他手动输入的组合提交。"""
    ask_registry.register("call_mix")
    response = client.post(
        _ask_url(generating_message),
        json={"call_id": "call_mix", "selected": ["方案A"], "text": "自定义"},
    )
    assert response.status_code == 200
    pending = ask_registry.get("call_mix")
    assert pending.selected == ["方案A"]
    assert pending.text == "自定义"

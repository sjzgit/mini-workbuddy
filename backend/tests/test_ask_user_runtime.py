"""ask_user 询问工具测试（specs/013-ask-user-tool，US1~US5）。

运行内等待/回答/取消/超时/无人值守经假流驱动的完整 Runtime；
治理（目录可见性）与端点契约经 TestClient。
"""

import asyncio
import json

import pytest

from app.models import AgentBinding
from app.services import generation_registry
from app.services.agent_runtime import (
    RunHistoryMessage,
    RunLimits,
    RunRequest,
    execute_run,
)
from app.services.agent_runtime import ask_user as ask_registry
from app.services.agent_runtime.ask_user import format_answer_text
from app.services.agent_runtime.tools import _begin_ask_user, _summary  # noqa: F401
from app.services.openai_client import ToolCallDelta

from tests.test_agent_runtime_fixtures import (
    bind,
    collect_events,
    content_round,
    event_names,
    fake_runtime_stream,
    runtime_db,
    tool_call_round,
)
from tests.test_agent_runtime_fixtures import runtime_tools_dir  # noqa: F401

pytestmark = pytest.mark.anyio


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param


def make_request(agent_id: int, message: str = "问题",
                 history: list | None = None) -> RunRequest:
    rows = [RunHistoryMessage(role="user", content=message)] if history is None else history
    return RunRequest(agent_id=agent_id, user_message="" if history is None else message,
                      history=rows, limits=RunLimits())


def ask_user_round(arguments: str, call_id: str = "call_ask_1") -> list:
    return tool_call_round("ask_user", arguments, call_id)


@pytest.fixture
def clean_ask_registry():
    """测试前后清空挂起注册表（零残留不变量的前提）。"""
    ask_registry._registry.clear()
    yield
    ask_registry._registry.clear()


async def _find(events, name: str):
    """取首个指定事件；无则 None。"""
    for event in events:
        if event.event == name:
            return event
    return None


class TestGovernance:
    """US1：治理——目录可见性（绑定 × 启用）。"""

    async def test_ask_user_in_catalog_when_bound_and_enabled(
        self, db_session, seed_agent, tools_seeded, runtime_db,
    ) -> None:
        from app.models import ToolEntry
        from app.services.agent_runtime.tools import build_tool_catalog

        tool = db_session.query(ToolEntry).filter_by(name="ask_user").first()
        bind(db_session, seed_agent.id, "tool", tool.id)

        catalog, _skills = build_tool_catalog(db_session, seed_agent.id, RunLimits())
        assert any(c.ref == "ask_user" for c in catalog)

    async def test_not_in_catalog_when_unbound(
        self, db_session, seed_agent, tools_seeded,
    ) -> None:
        from app.services.agent_runtime.tools import build_tool_catalog

        catalog, _skills = build_tool_catalog(db_session, seed_agent.id, RunLimits())
        assert not any(c.ref == "ask_user" for c in catalog)

    async def test_not_in_catalog_when_disabled(
        self, db_session, seed_agent, tools_seeded,
    ) -> None:
        from app.models import ToolEntry
        from app.services.agent_runtime.tools import build_tool_catalog

        tool = db_session.query(ToolEntry).filter_by(name="ask_user").first()
        bind(db_session, seed_agent.id, "tool", tool.id)
        tool.enabled = False
        db_session.commit()

        catalog, _skills = build_tool_catalog(db_session, seed_agent.id, RunLimits())
        assert not any(c.ref == "ask_user" for c in catalog)


class TestParamValidation:
    """参数校验与空选项降级（Edge Cases）。"""

    def test_missing_question_invalid(self) -> None:
        from app.services.tool_registry import AskUserParams

        with pytest.raises(Exception):
            AskUserParams(**{})

    def test_empty_options_degrades_to_open(self) -> None:
        from app.services.tool_registry import AskUserParams

        params = AskUserParams(question="?", options=[])
        assert params.options is None  # 降级开放式

    def test_options_over_limit_rejected(self) -> None:
        from app.services.tool_registry import AskUserParams

        with pytest.raises(Exception):
            AskUserParams(question="?", options=[f"项{i}" for i in range(11)])

    def test_option_too_long_rejected(self) -> None:  # noqa: ANN201
        from app.services.tool_registry import AskUserParams

        with pytest.raises(Exception):
            AskUserParams(question="?", options=["x" * 201])


class TestFormatAnswerText:
    """回答文本格式（契约 §4 主定义）。"""

    def test_open_answer(self) -> None:
        assert format_answer_text([], "自定义回答") == "自定义回答"

    def test_single_option(self) -> None:
        assert format_answer_text(["方案A"], None) == "方案A"

    def test_multi_options_joined(self) -> None:
        assert format_answer_text(["方案A", "方案C"], None) == "方案A、方案C"

    def test_other_only(self) -> None:
        assert format_answer_text([], "手写内容") == "手写内容"

    def test_options_plus_other(self) -> None:
        assert format_answer_text(["方案A", "其他，我手动输入"], "手写内容") == (
            "方案A、其他，我手动输入；其他：手写内容"
        )


class TestAskFlow:
    """US2/US3：端到端——挂起、事件、回答恢复、取消、超时、无人值守。"""

    async def test_ask_user_full_flow_via_runtime(
        self, db_session, seed_agent, tools_seeded, runtime_db,
        fake_runtime_stream, clean_ask_registry,
    ) -> None:
        from app.models import ToolEntry

        tool = db_session.query(ToolEntry).filter_by(name="ask_user").first()
        bind(db_session, seed_agent.id, "tool", tool.id)

        fake_runtime_stream.script(
            ask_user_round(json.dumps({"question": "用于什么场合？"}, ensure_ascii=False)),
            content_round("好的，按你的回答生成"),
        )
        request = make_request(seed_agent.id, "帮我写自我介绍")
        request.reply_message_id = 999  # 有聊天界面在场（区别于评测直调）
        gen = execute_run(request).__aiter__()
        events: list = []

        async def consume() -> None:
            async for event in gen:
                events.append(event)
                if event.event == "ask_user":
                    # 模拟用户回答：事件到达后提交
                    await asyncio.sleep(0)
                    call_id = event.data["call_id"]
                    assert ask_registry.submit_answer(
                        call_id, [], "求职面试",
                    )
                elif event.event == "run_completed":
                    return

        await asyncio.wait_for(consume(), timeout=5)
        names = [e.event for e in events]
        assert "ask_user" in names
        ask_event = await _find(events, "ask_user")
        assert ask_event.data["question"] == "用于什么场合？"
        assert ask_event.data["options"] == []  # 开放式
        assert ask_event.data["multi_select"] is False

        tool_completed = await _find(events, "tool_call_completed")
        assert tool_completed.data["status"] == "success"
        assert tool_completed.data["result"] == "求职面试"  # 回答文本交还模型（契约 §4）
        assert events[-1].data["status"] == "completed"
        assert ask_registry.pending_count() == 0  # 零残留

    async def test_cancel_during_wait(
        self, db_session, seed_agent, tools_seeded, runtime_db,
        fake_runtime_stream, clean_ask_registry,
    ) -> None:
        from app.models import ToolEntry

        tool = db_session.query(ToolEntry).filter_by(name="ask_user").first()
        bind(db_session, seed_agent.id, "tool", tool.id)

        fake_runtime_stream.script(
            ask_user_round('{"question": "继续吗？"}'),
        )
        request = make_request(seed_agent.id)
        request.reply_message_id = 999  # 有界面在场；等待中取消
        events: list = []

        async def consume() -> None:
            async for event in execute_run(request):
                events.append(event)

        task = asyncio.create_task(consume())
        # 等挂起出现后取消（等待中停止，FR-011）
        for _ in range(500):
            if ask_registry.pending_count() > 0:
                break
            await asyncio.sleep(0.01)
        request.cancel.set()
        await asyncio.wait_for(task, timeout=5)

        completed = events[-1]
        assert completed.data["status"] == "cancelled"
        assert ask_registry.pending_count() == 0  # 零残留
        tool_completed = None
        for event in events:
            if event.event == "tool_call_completed":
                tool_completed = event
        assert tool_completed is not None
        assert tool_completed.data["status"] == "cancelled"

    async def test_timeout(
        self, db_session, seed_agent, tools_seeded, runtime_db,
        fake_runtime_stream, clean_ask_registry, monkeypatch,
    ) -> None:
        from app.models import ToolEntry

        tool = db_session.query(ToolEntry).filter_by(name="ask_user").first()
        bind(db_session, seed_agent.id, "tool", tool.id)
        monkeypatch.setattr("app.core.config.settings.ask_user_timeout_seconds", 0)
        fake_runtime_stream.script(
            ask_user_round('{"question": "还在吗？"}'),
            content_round("继续"),
        )
        request = make_request(seed_agent.id)
        request.reply_message_id = 999  # 有界面在场
        events = await collect_events(request)
        tool_completed = await _find(events, "tool_call_completed")
        assert tool_completed.data["status"] == "error"
        assert "未在 0 秒内回答" in tool_completed.data["result"]
        assert ask_registry.pending_count() == 0

    async def test_unattended_run_no_suspend(
        self, db_session, seed_agent, tools_seeded, runtime_db,
        fake_runtime_stream, clean_ask_registry,
    ) -> None:
        """评测直调（reply_message_id=None）：不挂起、立即失败结果、零残留（FR-014）。"""
        from app.models import ToolEntry

        tool = db_session.query(ToolEntry).filter_by(name="ask_user").first()
        bind(db_session, seed_agent.id, "tool", tool.id)

        fake_runtime_stream.script(
            ask_user_round('{"question": "选哪个？"}'),
            content_round("好的，我自行决定"),
        )
        request = make_request(seed_agent.id)
        request.reply_message_id = None  # 评测直调形态（009 契约）
        events = await collect_events(request)

        ask_event = await _find(events, "ask_user")
        assert ask_event is None  # 不发询问事件
        tool_completed = await _find(events, "tool_call_completed")
        assert tool_completed.data["status"] == "error"
        assert "没有用户可以回答" in tool_completed.data["result"]
        assert ask_registry.pending_count() == 0

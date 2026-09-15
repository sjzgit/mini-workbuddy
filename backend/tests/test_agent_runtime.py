"""统一 Agent Runtime 测试（specs/009-agent-runtime，US1~US6）。

假流驱动（research R12）：FakeRuntimeStream 脚本化模型行为，覆盖直答、工具循环、
Skill 加载、轮数收尾、权限拒绝、取消清理、事件契约与并发隔离。
真实模型/MCP 交互不在测试范围。
"""

import asyncio
import json
import time

import pytest

from app.models import AgentBinding, MessageEntry
from app.services import generation_registry
from app.services.generation_registry import StreamEvent
from app.services.agent_runtime import (
    RunHistoryMessage,
    RunLimits,
    RunRequest,
    execute_run,
)
from app.services.agent_runtime import runtime as rt_module
from app.services.agent_runtime.events import (
    EVENT_CONTENT_DELTA,
    EVENT_MODEL_REQUEST_COMPLETED,
    EVENT_MODEL_REQUEST_STARTED,
    EVENT_REASONING_DELTA,
    EVENT_RUN_COMPLETED,
    EVENT_RUN_STARTED,
    EVENT_TOOL_CALL_COMPLETED,
    EVENT_TOOL_CALL_STARTED,
)
from app.services.openai_client import (
    ChatHttpError,
    ContentDelta,
    ReasoningDelta,
    ToolCallDelta,
    UsageInfo,
)

from tests.test_agent_runtime_fixtures import (
    bind,
    collect_events,
    content_round,
    event_names,
    fake_runtime_stream,
    runtime_db,
    runtime_tools_dir,  # noqa: F401 — 隔离授权目录
    seq_list,
    tool_call_round,
    usage_info,
    write_skill,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param


def make_request(agent_id: int, message: str = "问题", history: list | None = None,
                 limits: RunLimits | None = None) -> RunRequest:
    rows = [RunHistoryMessage(role="user", content=message)] if history is None else history
    return RunRequest(agent_id=agent_id, user_message="" if history is None else message,
                      history=rows, limits=limits or RunLimits())


class TestEventContract:
    """T011：事件契约基础——seq 递增、终态恰一次、usage 未知为 None。"""

    async def test_direct_answer_event_sequence(
        self, db_session, seed_agent, fake_runtime_stream, runtime_db,
    ) -> None:
        fake_runtime_stream.script(content_round("回答A") + [usage_info()])
        events = await collect_events(make_request(seed_agent.id))
        names = event_names(events)
        assert names == [
            EVENT_RUN_STARTED, EVENT_MODEL_REQUEST_STARTED,
            EVENT_CONTENT_DELTA, EVENT_MODEL_REQUEST_COMPLETED, EVENT_RUN_COMPLETED,
        ]
        assert seq_list(events) == [1, 2, 3, 4, 5]
        assert len({e.run_id for e in events}) == 1  # run_id 唯一且一致
        completed = events[-1].data
        assert completed["status"] == "completed"
        assert completed["message"] is None  # Runtime 不落库，桥接层回填
        assert completed["content_text"] == "回答A"

    async def test_usage_none_means_unknown_not_zero(
        self, db_session, seed_agent, fake_runtime_stream, runtime_db,
    ) -> None:
        fake_runtime_stream.script(content_round("x") + [UsageInfo(None, None, None)])
        events = await collect_events(make_request(seed_agent.id))
        model_completed = next(e for e in events if e.event == EVENT_MODEL_REQUEST_COMPLETED)
        assert model_completed.data["usage"] == {
            "prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
        }
        assert events[-1].data["usage_total"] == {
            "prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
        }

    async def test_usage_partial_merge(
        self, db_session, seed_agent, fake_runtime_stream, runtime_db,
    ) -> None:
        fake_runtime_stream.script(
            content_round("a") + [usage_info(10, None, None)],
            content_round("b") + [usage_info(None, 5, None)],
        )
        # 第一轮无工具 → completed，第二脚本轮不消费；这里只验证未知传播
        events = await collect_events(make_request(seed_agent.id))
        assert events[-1].data["usage_total"]["prompt_tokens"] == 10
        assert events[-1].data["usage_total"]["completion_tokens"] is None

    async def test_reasoning_delta_order(
        self, db_session, seed_agent, fake_runtime_stream, runtime_db,
    ) -> None:
        fake_runtime_stream.script(
            [ReasoningDelta(text="想"), ContentDelta(text="答"), ReasoningDelta(text="又想")]
        )
        events = await collect_events(make_request(seed_agent.id))
        deltas = [e for e in events if e.event in (EVENT_REASONING_DELTA, EVENT_CONTENT_DELTA)]
        assert [(e.event, e.data["text"]) for e in deltas] == [
            (EVENT_REASONING_DELTA, "想"),
            (EVENT_CONTENT_DELTA, "答"),
            (EVENT_REASONING_DELTA, "又想"),
        ]
        assert events[-1].data["reasoning_text"] == "想又想"

    async def test_system_prompt_and_history_once(
        self, db_session, seed_agent, fake_runtime_stream, runtime_db,
    ) -> None:
        fake_runtime_stream.script(content_round("ok"))
        history = [
            RunHistoryMessage(role="user", content="第一问"),
            RunHistoryMessage(role="assistant", content="第一答"),
            RunHistoryMessage(role="user", content="第二问"),
        ]
        req = RunRequest(agent_id=seed_agent.id, user_message="第二问", history=history)
        await collect_events(req)
        sent = fake_runtime_stream.calls[0]["messages"]
        assert sent[0]["role"] == "system"
        assert sent[0]["content"] == "你是一个测试助手。"
        contents = [m["content"] for m in sent[1:]]
        assert contents.count("第二问") == 1  # FR-016 仅出现一次
        assert contents == ["第一问", "第一答", "第二问"]


class TestToolLoop:
    """T021：工具循环、跨轮正文保留、轮数收尾、幻觉拒绝。"""

    async def test_single_tool_call_round(
        self, db_session, seed_agent, seed_model, tools_seeded,
        fake_runtime_stream, runtime_db,
    ) -> None:
        from app.models import ToolEntry

        tool = db_session.query(ToolEntry).filter(ToolEntry.name == "current_time").first()
        bind(db_session, seed_agent.id, "tool", tool.id)
        fake_runtime_stream.script(
            tool_call_round("current_time", "{}"),
            content_round("现在时间是…") + [usage_info()],
        )
        events = await collect_events(make_request(seed_agent.id))
        names = event_names(events)
        assert EVENT_TOOL_CALL_STARTED in names and EVENT_TOOL_CALL_COMPLETED in names
        started = next(e for e in events if e.event == EVENT_TOOL_CALL_STARTED)
        completed = next(e for e in events if e.event == EVENT_TOOL_CALL_COMPLETED)
        assert started.data["call_id"] == completed.data["call_id"]  # 配对 FR-033
        assert started.data["tool_type"] == "builtin"
        assert completed.data["status"] in ("success", "error")  # 假 time_tool 可真实执行
        assert events[-1].data["status"] == "completed"
        # 工具结果进入模型上下文（role=tool）
        second_call = fake_runtime_stream.calls[1]["messages"]
        assert any(m.get("role") == "tool" for m in second_call)

    async def test_content_preserved_across_rounds(
        self, db_session, seed_agent, tools_seeded,
        fake_runtime_stream, runtime_db,
    ) -> None:
        from app.models import ToolEntry

        tool = db_session.query(ToolEntry).filter(ToolEntry.name == "current_time").first()
        bind(db_session, seed_agent.id, "tool", tool.id)
        fake_runtime_stream.script(
            [ContentDelta(text="先说打算。"), ToolCallDelta(index=0, id="c1", name="current_time", arguments_fragment="{}")],
            content_round("再给结论。"),
        )
        events = await collect_events(make_request(seed_agent.id))
        texts = [e.data["text"] for e in events if e.event == EVENT_CONTENT_DELTA]
        assert texts == ["先说打算。", "再给结论。"]  # FR-013 跨轮保留
        assert events[-1].data["content_text"] == "先说打算。再给结论。"

    async def test_max_rounds_final_answer(
        self, db_session, seed_agent, tools_seeded,
        fake_runtime_stream, runtime_db,
    ) -> None:
        from app.models import ToolEntry

        tool = db_session.query(ToolEntry).filter(ToolEntry.name == "current_time").first()
        bind(db_session, seed_agent.id, "tool", tool.id)
        db_session.get(seed_agent.__class__, seed_agent.id).max_rounds = 1
        db_session.commit()
        fake_runtime_stream.script(
            tool_call_round("current_time", "{}"),
            content_round("基于已有信息：无法确定时间。"),
        )
        events = await collect_events(make_request(seed_agent.id))
        assert events[-1].data["status"] == "max_rounds"
        assert events[-1].data["content_text"] == "基于已有信息：无法确定时间。"
        # 收尾请求不带 tools（FR-012）
        assert fake_runtime_stream.calls[1]["tools"] is None
        # 收尾轮次 = max_rounds + 1
        final_model_events = [e for e in events if e.event == EVENT_MODEL_REQUEST_STARTED]
        assert final_model_events[-1].data["round"] == 2

    async def test_hallucinated_tool_denied_but_run_continues(
        self, db_session, seed_agent, fake_runtime_stream, runtime_db,
    ) -> None:
        fake_runtime_stream.script(
            tool_call_round("不存在的工具", "{}"),
            content_round("好的，我直接回答。"),
        )
        events = await collect_events(make_request(seed_agent.id))
        completed_tool = next(e for e in events if e.event == EVENT_TOOL_CALL_COMPLETED)
        assert completed_tool.data["status"] == "denied"
        assert events[-1].data["status"] == "completed"  # 运行继续（Edge Cases）

    async def test_rounds_limit_narrowing(
        self, db_session, seed_agent, tools_seeded,
        fake_runtime_stream, runtime_db,
    ) -> None:
        from app.models import ToolEntry

        tool = db_session.query(ToolEntry).filter(ToolEntry.name == "current_time").first()
        bind(db_session, seed_agent.id, "tool", tool.id)
        db_session.get(seed_agent.__class__, seed_agent.id).max_rounds = 10
        db_session.commit()
        fake_runtime_stream.script(
            tool_call_round("current_time", "{}"),
            content_round("收尾"),
        )
        limits = RunLimits(max_rounds=1)
        events = await collect_events(make_request(seed_agent.id, limits=limits))
        assert events[-1].data["status"] == "max_rounds"  # min(10,1)=1 生效


class TestErrorPaths:
    """模型请求失败 → error 事件 + 终态（沿用 008 分类）。"""

    async def test_http_error_classified(
        self, db_session, seed_agent, fake_runtime_stream, runtime_db,
    ) -> None:
        fake_runtime_stream.script(ChatHttpError(401, "invalid api key"))
        events = await collect_events(make_request(seed_agent.id))
        names = event_names(events)
        assert "error" in names
        error = next(e for e in events if e.event == "error")
        assert error.data["category"] == "auth_error"
        assert "密钥" in error.data["message"]
        assert events[-1].event == EVENT_RUN_COMPLETED
        assert events[-1].data["status"] == "error"

    async def test_empty_response_is_error(
        self, db_session, seed_agent, fake_runtime_stream, runtime_db,
    ) -> None:
        fake_runtime_stream.script([])  # 无任何增量
        events = await collect_events(make_request(seed_agent.id))
        assert events[-1].data["status"] == "error"

    async def test_agent_unavailable_fallback_terminal(
        self, db_session, fake_runtime_stream, runtime_db,
    ) -> None:
        events = await collect_events(make_request(agent_id=99999))
        assert events[-1].event == EVENT_RUN_COMPLETED
        assert events[-1].data["status"] == "error"


class TestCancellation:
    """T031/T032：取消与清理（无 MCP 时的基础路径）。"""

    async def test_cancel_event_mid_stream(
        self, db_session, seed_agent, fake_runtime_stream, runtime_db,
    ) -> None:
        cancel = asyncio.Event()
        fake_runtime_stream.script(
            [ContentDelta(text="开头"), generation_registry_marker(), ContentDelta(text="不该出现")]
        )
        req = make_request(seed_agent.id)
        req.cancel = cancel

        async def set_cancel():
            await asyncio.sleep(0.05)
            cancel.set()
            fake_runtime_stream.unblocked = True  # 解除阻塞让流推进到下一个增量检查点

        async def run():
            return await collect_events(req)

        got, _ = await asyncio.gather(run(), set_cancel())
        events = got
        assert events[-1].event == EVENT_RUN_COMPLETED
        assert events[-1].data["status"] == "cancelled"
        assert events[-1].data["stopped"] is True
        texts = "".join(e.data["text"] for e in events if e.event == EVENT_CONTENT_DELTA)
        assert "不该出现" not in texts


def generation_registry_marker():
    """阻塞哨兵：使用 FakeRuntimeStream 识别的 BLOCK 字符串。"""
    from tests.test_agent_runtime_fixtures import BLOCK

    return BLOCK


class TestSkillLoading:
    """T026：Skill 目录 XML、load_skill 成功与各失败路径。"""

    @pytest.fixture
    def skill_agent(self, db_session, seed_agent, seed_model, tools_seeded, skills_dir):
        write_skill(skills_dir, "demo-skill", "演示技能", "用于演示", "按步骤执行：1) 思考 2) 回答")
        from app.models import SkillEntry

        skill = SkillEntry(dir_name="demo-skill", enabled=True)
        db_session.add(skill)
        db_session.commit()
        bind(db_session, seed_agent.id, "skill", skill.id)
        return seed_agent

    async def test_catalog_xml_in_system_prompt(
        self, db_session, skill_agent, fake_runtime_stream, runtime_db, skills_dir,
    ) -> None:
        fake_runtime_stream.script(content_round("好"))
        await collect_events(make_request(skill_agent.id))
        sent = fake_runtime_stream.calls[0]["messages"]
        system = sent[0]["content"]
        assert "<skill>" in system
        assert "Name: 演示技能" in system
        assert "ID: demo-skill" in system
        assert "Description: 用于演示" in system
        assert "load_skill" in system  # 按需加载指引

    async def test_load_skill_success(
        self, db_session, skill_agent, fake_runtime_stream, runtime_db, skills_dir,
    ) -> None:
        fake_runtime_stream.script(
            tool_call_round("load_skill", json.dumps({"skill_id": "demo-skill"})),
            content_round("按指令完成"),
        )
        events = await collect_events(make_request(skill_agent.id))
        started = next(e for e in events if e.event == EVENT_TOOL_CALL_STARTED)
        assert started.data["tool_type"] == "skill"
        completed = next(e for e in events if e.event == EVENT_TOOL_CALL_COMPLETED)
        assert completed.data["status"] == "success"
        # 指令全文进入模型上下文（FR-038：模型上下文完整、事件摘要）
        tool_msgs = [m for m in fake_runtime_stream.calls[1]["messages"] if m.get("role") == "tool"]
        assert any("按步骤执行" in m["content"] for m in tool_msgs)
        assert completed.data["result_summary"].startswith("按步骤执行") or len(completed.data["result_summary"]) <= 200

    async def test_no_skill_no_load_skill_tool(
        self, db_session, seed_agent, fake_runtime_stream, runtime_db,
    ) -> None:
        fake_runtime_stream.script(content_round("ok"))
        await collect_events(make_request(seed_agent.id))
        tools = fake_runtime_stream.calls[0]["tools"]
        assert tools is None or all(
            t["function"]["name"] != "load_skill" for t in (tools or [])
        )

    async def test_skill_disabled_after_catalog(
        self, db_session, skill_agent, fake_runtime_stream, runtime_db, skills_dir,
    ) -> None:
        from app.models import SkillEntry

        from tests.test_agent_runtime_fixtures import BLOCK

        fake_runtime_stream.script(
            [BLOCK, *tool_call_round("load_skill", json.dumps({"skill_id": "demo-skill"}))],
            content_round("那我直接回答"),
        )
        # 目录构建后、执行前停用（执行前 DB 复核，FR-016/023）
        async def disable_midway():
            while fake_runtime_stream.unblocked:
                await asyncio.sleep(0.01)  # 等待运行进入第一轮阻塞点
            row = db_session.query(SkillEntry).filter(SkillEntry.dir_name == "demo-skill").first()
            row.enabled = False
            db_session.commit()
            fake_runtime_stream.unblocked = True  # 放行，让 load_skill 在停用后执行

        async def run():
            return await collect_events(make_request(skill_agent.id))

        events, _ = await asyncio.gather(run(), disable_midway())
        completed = next(e for e in events if e.event == EVENT_TOOL_CALL_COMPLETED)
        assert completed.data["status"] == "denied"

    async def test_skill_not_found_and_path_rejected(
        self, db_session, skill_agent, fake_runtime_stream, runtime_db, skills_dir,
    ) -> None:
        fake_runtime_stream.script(
            tool_call_round("load_skill", json.dumps({"skill_id": "../../etc"})),
            content_round("明白"),
        )
        events = await collect_events(make_request(skill_agent.id))
        completed = next(e for e in events if e.event == EVENT_TOOL_CALL_COMPLETED)
        assert completed.data["status"] == "denied"

    async def test_skill_too_large_rejected_not_truncated(
        self, db_session, skill_agent, fake_runtime_stream, runtime_db, skills_dir,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.core.config import settings

        monkeypatch.setattr(settings, "runtime_skill_max_bytes", 10)
        fake_runtime_stream.script(
            tool_call_round("load_skill", json.dumps({"skill_id": "demo-skill"})),
            content_round("了解"),
        )
        events = await collect_events(make_request(skill_agent.id))
        completed = next(e for e in events if e.event == EVENT_TOOL_CALL_COMPLETED)
        assert completed.data["status"] == "denied"


class TestConcurrency:
    """T034：并发运行隔离与会话互斥沿用注册表（FR-039~043）。"""

    async def test_parallel_runs_isolated(
        self, db_session, seed_agent, seed_model, tools_seeded,
        fake_runtime_stream, runtime_db,
    ) -> None:
        fake_runtime_stream.script(content_round("A1"), content_round("A2"))
        req1 = make_request(seed_agent.id, "第一")
        req2 = make_request(seed_agent.id, "第二")
        results = await asyncio.gather(collect_events(req1), collect_events(req2))
        ev1, ev2 = results
        assert {e.run_id for e in ev1}.isdisjoint({e.run_id for e in ev2})
        assert seq_list(ev1) == list(range(1, len(ev1) + 1))
        assert seq_list(ev2) == list(range(1, len(ev2) + 1))
        c1 = [e.data["text"] for e in ev1 if e.event == EVENT_CONTENT_DELTA]
        c2 = [e.data["text"] for e in ev2 if e.event == EVENT_CONTENT_DELTA]
        assert c1 == ["A1"] and c2 == ["A2"]  # 剧本按调用序弹出，事件互不串扰

    async def test_registry_session_mutex_still_works(self, db_session, seed_agent) -> None:
        from app.services.generation_registry import GenerationRegistry

        registry = GenerationRegistry()
        task = generation_registry.GenerationTask(conversation_id=7, reply_message_id=1)
        registry.register(task)
        assert registry.get_running_by_conversation(7) is task
        task.terminal_event = StreamEvent(event="run_completed", data="{}")
        assert registry.get_running_by_conversation(7) is None


class TestMcpConnectionLifecycle:
    """防回归（FR-029）：MCP 上下文进入与退出必须同 task（anyio cancel scope 归属）。

    背景：connect_mcp_servers 曾用 asyncio.wait_for 包装 _connect_one——wait_for
    把协程放进临时 Task，stdio_client 的 cancel scope 归属临时 Task；运行结束
    aclose 在桥接 Task 退出时抛
    "RuntimeError: Attempted to exit a cancel scope that isn't the current task's..."，
    MCP 子进程无法清理。修复后用 asyncio.timeout（不换 Task）。
    用真实 fake_mcp_server（stdio）验证：连接 → 列工具 → aclose 全程无异常。
    """

    async def test_connect_and_close_same_task_clean(
        self, db_session, seed_resources, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import sys
        from pathlib import Path as _Path

        from app.models import McpServerEntry

        sys_path = _Path(__file__).parent
        sys.path.insert(0, str(sys_path))
        from fake_mcp_server import __file__ as fake_server_path  # noqa: E402

        entry = McpServerEntry(
            name="lifecycle-fake",
            server_type="stdio",
            command=sys.executable,
            command_args=[str(_Path(fake_server_path)), "--tools", "2"],
            enabled=True,
        )
        db_session.add(entry)
        db_session.commit()

        from app.core.config import settings

        monkeypatch.setattr(settings, "runtime_mcp_connect_timeout_seconds", 15)
        from app.services.agent_runtime.tools import connect_mcp_servers

        sessions, stacks, tools_by_server = await connect_mcp_servers(db_session, [entry.id])
        assert entry.id in sessions, "stdio 假 Server 应连接成功"
        assert len(tools_by_server.get(entry.id, [])) == 2

        # 同 task 内关闭栈：修复前这里抛 RuntimeError（cancel scope 归属）
        for stack in stacks.values():
            await stack.aclose()


class TestToolDisplayFields:
    """010（工具过程展示）：工具事件增补字段契约——易读名、Server 名、截断与人话失败。"""

    async def test_builtin_display_name_and_params(
        self, db_session, seed_agent, tools_seeded, fake_runtime_stream, runtime_db,
    ) -> None:
        from app.models import ToolEntry

        tool = db_session.query(ToolEntry).filter(ToolEntry.name == "current_time").first()
        bind(db_session, seed_agent.id, "tool", tool.id)
        fake_runtime_stream.script(
            tool_call_round("current_time", "{}"),
            content_round("好的") + [usage_info()],
        )
        events = await collect_events(make_request(seed_agent.id))
        started = next(e for e in events if e.event == EVENT_TOOL_CALL_STARTED)
        completed = next(e for e in events if e.event == EVENT_TOOL_CALL_COMPLETED)
        assert started.data["params"] == "{}"
        assert started.data["display_name"] == "当前时间"
        assert started.data["server_name"] is None
        assert completed.data["display_name"] == "当前时间"
        assert completed.data["server_name"] is None
        assert completed.data["result"]  # 完整结果非空
        assert completed.data["status"] == "success"

    async def test_mcp_display_info_resolution(self, db_session) -> None:
        """MCP 分支：display_name=原工具名，server_name=Server 显示名（单元级）。"""
        from app.models import McpServerEntry
        from app.services.agent_runtime.tools import ToolCatalogEntry, _display_info

        server = McpServerEntry(name="GitHub", server_type="stdio", enabled=True)
        db_session.add(server)
        db_session.commit()
        entry = ToolCatalogEntry(
            exposed_name="mcp__GitHub__create_issue", tool_type="mcp",
            description=None, parameters={}, ref="create_issue", server_id=server.id,
        )
        display_name, server_name = _display_info(entry, db_session)
        assert display_name == "create_issue"
        assert server_name == "GitHub"

    async def test_skill_display_name(self) -> None:
        """Skill 分支：固定易读名"加载 Skill"。"""
        from app.services.agent_runtime.tools import ToolCatalogEntry, _display_info

        entry = ToolCatalogEntry(
            exposed_name="load_skill", tool_type="skill",
            description=None, parameters={}, ref="demo",
        )
        display_name, server_name = _display_info(entry, None)  # type: ignore[arg-type]
        assert display_name == "加载 Skill"
        assert server_name is None

    async def test_params_truncation_marker(
        self, db_session, seed_agent, tools_seeded, fake_runtime_stream, runtime_db,
    ) -> None:
        from app.core.config import settings
        from app.models import ToolEntry

        tool = db_session.query(ToolEntry).filter(ToolEntry.name == "current_time").first()
        bind(db_session, seed_agent.id, "tool", tool.id)
        long_args = json.dumps({"q": "字" * 5000}, ensure_ascii=False)
        fake_runtime_stream.script(
            tool_call_round("current_time", long_args),
            content_round("好的") + [usage_info()],
        )
        events = await collect_events(make_request(seed_agent.id))
        started = next(e for e in events if e.event == EVENT_TOOL_CALL_STARTED)
        expected_tail = f"…[已截断，完整内容共 {len(long_args)} 字符]"
        assert started.data["params"].endswith(expected_tail)
        assert len(started.data["params"]) < len(long_args)
        assert settings.runtime_tool_params_max_chars == 4000  # 契约默认值生效

    async def test_failure_result_no_stacktrace(
        self, db_session, seed_agent, fake_runtime_stream, runtime_db,
    ) -> None:
        fake_runtime_stream.script(
            tool_call_round("不存在的工具", "{}"),
            content_round("好的，我直接回答。"),
        )
        events = await collect_events(make_request(seed_agent.id))
        completed = next(e for e in events if e.event == EVENT_TOOL_CALL_COMPLETED)
        assert completed.data["status"] == "denied"
        assert completed.data["result"].startswith("[tool_not_found]")
        assert "Traceback" not in completed.data["result"]
        assert completed.data["display_name"] == "不存在的工具"  # 目录外无易读名 → fallback 暴露名

    async def test_cancelled_record_still_has_display_sources(
        self, db_session, seed_agent, tools_seeded, runtime_db,
    ) -> None:
        """取消路径（run_tool 单元级）：params_full/result_full 仍被填充，
        display_name 允许为空（事件侧 fallback 暴露名）。"""
        import asyncio as _asyncio

        from app.services.agent_runtime.events import RunEventEmitter
        from app.services.agent_runtime.tools import ToolContext, run_tool

        cancel = _asyncio.Event()
        cancel.set()
        emitter = RunEventEmitter(run_id="run_test")
        ctx = ToolContext(run_request=make_request(seed_agent.id), emitter=emitter, cancel=cancel)
        record = await run_tool("current_time", '{"tz": "UTC"}', ctx, db_session)
        assert record.status == "cancelled"
        assert record.params_full == '{"tz": "UTC"}'
        assert "运行已取消" in record.result_full

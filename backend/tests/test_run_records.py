"""运行记录持久化测试（specs/011 FR-001~009、SC-001/002/004）。"""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    ConversationEntry,
    MessageEntry,
    RunEntry,
    RunEventEntry,
    RunPayloadEntry,
)
from app.services.run_service import INTERRUPTED_REASON, mark_interrupted_runs
from app.services.openai_client import ContentDelta, ReasoningDelta, ToolCallDelta

from tests.conftest import BLOCK, FakeStream
from tests.test_chat_stream import read_sse, wait_terminal


@pytest.fixture
def record_env(
    client: TestClient,
    db_session: Session,
    seed_agent,
    seed_conversation,
    fake_stream: FakeStream,
    chat_session_factory,
    runtime_db,
    recorder_db,
    tools_seeded,
    clean_registry,
):
    from app.models import AgentBinding, ToolEntry

    # tools_seeded 夹具已播种内置工具行
    tool = db_session.query(ToolEntry).filter(ToolEntry.name == "current_time").one()
    db_session.add(AgentBinding(
        agent_id=seed_agent.id, resource_type="tool", resource_id=tool.id,
    ))
    db_session.commit()
    return {
        "client": client, "db": db_session,
        "agent": seed_agent, "conversation": seed_conversation,
        "fake": fake_stream,
    }



class RoundsStream:
    """按轮次脚本的假流：第 N 次调用用第 N 组步骤（末组复用）。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.rounds: list[list] = []

    def script_rounds(self, *rounds: list) -> None:
        self.rounds = [list(r) for r in rounds]

    async def __call__(self, base_url, model_identifier, api_key, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        for step in self.rounds[idx]:
            if isinstance(step, Exception):
                raise step
            yield step


def _use_rounds(monkeypatch, stream: RoundsStream) -> RoundsStream:
    from app.services.agent_runtime import compression, runtime

    monkeypatch.setattr(runtime, "stream_chat_completion", stream)
    monkeypatch.setattr(compression, "stream_chat_completion", stream)
    return stream


def _bind_tool(db: Session, agent_id: int, tool_name: str) -> None:
    """给 Agent 绑定内置工具（测试用）。"""
    from app.models import AgentBinding, ToolEntry

    tool = db.query(ToolEntry).filter(ToolEntry.name == tool_name).one()
    db.add(AgentBinding(agent_id=agent_id, resource_type="tool", resource_id=tool.id))
    db.commit()


def _send(client, cid, content):
    return client.post(f"/api/conversations/{cid}/messages", json={"content": content})


def _runs(db: Session) -> list[RunEntry]:
    return list(db.query(RunEntry).all())


def _events(db: Session, run_id: str) -> list[RunEventEntry]:
    return list(
        db.query(RunEventEntry)
        .filter(RunEventEntry.run_id == run_id)
        .order_by(RunEventEntry.seq)
        .all()
    )


def _payloads(db: Session, run_id: str) -> list[RunPayloadEntry]:
    return list(db.query(RunPayloadEntry).filter(RunPayloadEntry.run_id == run_id).all())


def _successful_run(db: Session) -> RunEntry:
    rows = [r for r in _runs(db) if r.status == "succeeded"]
    assert rows, "没有成功运行"
    return rows[-1]


class TestPersistenceBasics:
    def test_successful_run_persisted(self, record_env) -> None:
        env = record_env
        env["fake"].script(ContentDelta(text="回答正文"))
        response = _send(env["client"], env["conversation"].id, "你好")
        assert response.status_code == 201
        reply_id = response.json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _successful_run(env["db"])
        assert run.run_id
        assert run.agent_name == "测试助手"
        assert run.model_name == "GPT 测试模型"
        assert run.model_identifier == "gpt-test"
        assert run.conversation_id == env["conversation"].id
        assert run.reply_message_id == reply_id
        assert run.total_duration_ms is not None and run.total_duration_ms >= 0
        assert run.first_output_ms is not None and run.first_output_ms >= 0
        assert run.end_reason
        assert run.model_call_count == 1
        assert run.tool_call_count == 0

    def test_events_persisted_without_deltas(self, record_env) -> None:
        env = record_env
        env["fake"].script(
            ReasoningDelta(text="想想 "),
            ContentDelta(text="回答"),
            ContentDelta(text="正文"),
        )
        reply_id = _send(env["client"], env["conversation"].id, "问题") .json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _successful_run(env["db"])
        events = _events(env["db"], run.run_id)
        names = [e.event_type for e in events]
        # 结构性事件齐全；增量事件不落库（011 澄清决定）
        assert names[0] == "run_started"
        assert "reasoning_delta" not in names and "content_delta" not in names
        assert names[-1] == "run_completed"
        # data 无透传字段与 010 展示字段
        for e in events:
            for key in ("params_full", "result_full", "request_messages",
                        "output_full", "content_text", "reasoning_text"):
                assert key not in (e.data or {})
        assert events[0].data["agent_name"] == "测试助手"
        assert events[0].data["model_name"] == "GPT 测试模型"

    def test_payloads_persisted_sanitized(self, record_env, monkeypatch) -> None:
        env = record_env
        stream = _use_rounds(monkeypatch, RoundsStream())
        stream.script_rounds(
            [
                ContentDelta(text="查询中"),
                ToolCallDelta(index=0, id="call_1", name="current_time", arguments_fragment="{}"),
            ],
            [ContentDelta(text="当前时间为 12:00，完成")],
        )
        reply_id = _send(env["client"], env["conversation"].id, "现在几点").json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _successful_run(env["db"])
        assert run.tool_call_count == 1
        events = _events(env["db"], run.run_id)
        started = [e for e in events if e.event_type == "tool_call_started"]
        completed = [e for e in events if e.event_type == "tool_call_completed"]
        assert len(started) == 1 and len(completed) == 1
        assert started[0].call_id == completed[0].call_id
        payloads = {p.payload_type for p in _payloads(env["db"], run.run_id)}
        assert "tool_params" in payloads
        assert "tool_result" in payloads
        assert "model_input" in payloads
        assert "model_output" in payloads


class TestExitPaths:
    def test_cancelled_run_status(self, record_env) -> None:
        env = record_env
        env["fake"].script(ContentDelta(text="先输出一部分"), BLOCK)
        response = _send(env["client"], env["conversation"].id, "长任务")
        reply_id = response.json()["reply_message_id"]
        # 等任务真正启动（call 记录出现）
        deadline = time.time() + 2
        while time.time() < deadline and not env["fake"].calls:
            time.sleep(0.01)
        stop = env["client"].post(
            f"/api/conversations/{env['conversation'].id}/messages/{reply_id}/stop")
        assert stop.status_code == 200
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _runs(env["db"])[-1]
        assert run.status == "cancelled"
        assert "取消" in run.end_reason

    def test_model_error_run_failed(self, record_env) -> None:
        env = record_env
        env["fake"].script(ContentDelta(text="部分"), RuntimeError("boom"))
        reply_id = _send(env["client"], env["conversation"].id, "触发错误").json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _runs(env["db"])[-1]
        assert run.status == "failed"
        assert run.error_summary
        # 错误摘要不含内部细节
        assert "boom" not in (run.error_summary or "")
        # 消息保留未完成正文，状态 incomplete
        reply = env["db"].get(MessageEntry, reply_id)
        assert reply.status == "incomplete"
        assert reply.content == "部分"

    def test_denied_tool_not_counted(self, record_env, monkeypatch) -> None:
        env = record_env
        # 模型请求一个未绑定工具 → denied；不计入 tool_call_count（FR-014）
        stream = _use_rounds(monkeypatch, RoundsStream())
        stream.script_rounds(
            [
                ContentDelta(text="试试"),
                ToolCallDelta(index=0, id="c1", name="file_read_write", arguments_fragment="{}"),
            ],
            [ContentDelta(text="完毕")],
        )
        reply_id = _send(env["client"], env["conversation"].id, "用文件工具").json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _successful_run(env["db"])
        denied = [e for e in _events(env["db"], run.run_id)
                  if e.event_type == "tool_call_completed" and e.data.get("status") == "denied"]
        assert denied, "应有 denied 工具调用事件"
        assert run.tool_call_count == 0

    def test_interrupted_recovery(self, record_env) -> None:
        env = record_env
        env["fake"].script(ContentDelta(text="内容"))
        reply_id = _send(env["client"], env["conversation"].id, "开始").json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        # 手工造一条 running 记录，模拟服务重启遗留
        stuck = RunEntry(
            run_id="stuckrun0deadbeef", conversation_id=env["conversation"].id,
            reply_message_id=reply_id, agent_id=env["agent"].id,
            agent_name="测试助手", model_name="GPT 测试模型",
            model_identifier="gpt-test", status="running",
        )
        env["db"].add(stuck)
        env["db"].commit()
        count = mark_interrupted_runs(env["db"])
        env["db"].expunge_all()
        assert count >= 1
        row = env["db"].query(RunEntry).filter(RunEntry.run_id == "stuckrun0deadbeef").one()
        assert row.status == "failed"
        assert row.end_reason == INTERRUPTED_REASON


class TestRunListApi:
    def _seed_runs(self, env, count: int) -> None:
        from datetime import datetime, timedelta

        base = datetime(2026, 9, 1, 12, 0, 0)
        for i in range(count):
            env["db"].add(RunEntry(
                run_id=f"seed{i:020d}",
                conversation_id=env["conversation"].id,
                agent_id=env["agent"].id,
                agent_name="测试助手",
                model_name="GPT 测试模型",
                model_identifier="gpt-test",
                status="succeeded" if i % 3 else "failed",
                started_at=base + timedelta(minutes=i),
                end_reason="模型直接给出回答，运行正常结束" if i % 3 else "运行过程中发生错误",
                error_summary=None if i % 3 else "生成失败",
            ))
        env["db"].commit()

    def test_list_filter_pagination_order(self, record_env) -> None:
        env = record_env
        self._seed_runs(env, 7)
        resp = env["client"].get("/api/runs?page=1&page_size=5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 7
        assert len(body["items"]) == 5
        starts = [item["started_at"] for item in body["items"]]
        assert starts == sorted(starts, reverse=True)
        # 状态筛选
        resp = env["client"].get("/api/runs?status=failed")
        assert resp.json()["total"] == 3
        assert all(item["status"] == "failed" for item in resp.json()["items"])
        # Agent 筛选
        resp = env["client"].get(f"/api/runs?agent_id={env['agent'].id}")
        assert resp.json()["total"] == 7
        # 非法状态
        assert env["client"].get("/api/runs?status=bogus").status_code == 422
        # page_size 上限夹取
        assert env["client"].get("/api/runs?page_size=999").status_code == 200

    def test_tokens_null_when_unknown(self, record_env) -> None:
        env = record_env
        env["fake"].script(ContentDelta(text="回答"))
        reply_id = _send(env["client"], env["conversation"].id, "你好").json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _successful_run(env["db"])
        # 假流未返回 usage → NULL（禁止填 0，FR-015）
        assert run.prompt_tokens is None
        assert run.total_tokens is None

    def test_constant_query_count(self, record_env) -> None:
        """SC-003：相同分页条件下查询次数不随行数增长（COUNT+SELECT 共 2 条）。"""
        from sqlalchemy import event

        env = record_env
        self._seed_runs(env, 60)
        engine = env["db"].get_bind()
        counter = {"selects": 0}

        def _count(_conn, _cursor, statement, _params, _ctx, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                counter["selects"] += 1

        event.listen(engine, "before_cursor_execute", _count)
        try:
            env["client"].get("/api/runs?page=1&page_size=10")
            assert counter["selects"] == 2, f"10 行查询数 {counter['selects']}"
            counter["selects"] = 0
            env["client"].get("/api/runs?page=1&page_size=50")
            assert counter["selects"] == 2, f"50 行查询数 {counter['selects']}"
        finally:
            event.remove(engine, "before_cursor_execute", _count)


class TestRunDetailApi:
    def test_detail_events_and_payloads(self, record_env, monkeypatch) -> None:
        env = record_env
        stream = _use_rounds(monkeypatch, RoundsStream())
        stream.script_rounds(
            [ContentDelta(text="查"), ToolCallDelta(index=0, id="c1", name="current_time", arguments_fragment="{}")],
            [ContentDelta(text="12:00")],
        )
        reply_id = _send(env["client"], env["conversation"].id, "几点").json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _successful_run(env["db"])
        # 详情：摘要 + 事件（seq 升序）
        resp = env["client"].get(f"/api/runs/{run.run_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["summary"]["run_id"] == run.run_id
        seqs = [e["seq"] for e in detail["events"]]
        assert seqs == sorted(seqs)
        types = [e["event_type"] for e in detail["events"]]
        assert types[0] == "run_started" and types[-1] == "run_completed"
        assert "tool_call_started" in types and "tool_call_completed" in types
        # 载荷：默认列表不含 content
        resp = env["client"].get(f"/api/runs/{run.run_id}/payloads")
        assert resp.status_code == 200
        metas = resp.json()
        assert metas and all("content" not in m for m in metas)
        payload_types = {m["payload_type"] for m in metas}
        assert {"model_input", "model_output", "tool_params", "tool_result"} <= payload_types
        # 单条载荷返回全文
        target = next(m for m in metas if m["payload_type"] == "tool_params")
        resp = env["client"].get(f"/api/runs/{run.run_id}/payloads/{target['id']}")
        assert resp.status_code == 200
        assert resp.json()["content"]
        # 404
        assert env["client"].get("/api/runs/nonexistent").status_code == 404
        assert env["client"].get(f"/api/runs/{run.run_id}/payloads/99999").status_code == 404

    def test_conversation_runs(self, record_env) -> None:
        env = record_env
        env["fake"].script(ContentDelta(text="回答"))
        _send(env["client"], env["conversation"].id, "你好")
        resp = env["client"].get(f"/api/conversations/{env['conversation'].id}/runs")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert env["client"].get("/api/conversations/999999/runs").status_code == 404


class TestIntegrityAndCascade:
    def test_duplicate_event_seq_skipped(self, record_env) -> None:
        """E1/FR-008：同 (run_id, seq) 重复投递被幂等跳过，不重复插入。"""
        env = record_env
        env["fake"].script(ContentDelta(text="回答"))
        reply_id = _send(env["client"], env["conversation"].id, "你好").json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _successful_run(env["db"])
        before = len(_events(env["db"], run.run_id))
        # 通过 RunRecorder 重放一条同 run_id/seq 的事件（模拟重复投递）
        from app.services.agent_runtime import recorder as recorder_mod
        from app.services.agent_runtime.events import RunEvent
        from app.schemas.agent_runtime import ErrorEventData

        recorder = recorder_mod.RunRecorder(
            run.run_id,
            conversation_id=run.conversation_id,
            reply_message_id=run.reply_message_id,
            agent_id=run.agent_id,
        )
        replay = RunEvent(
            event="error", seq=1, run_id=run.run_id,
            round=None, call_id=None,
            data={"run_id": run.run_id, "seq": 1, "category": "unknown", "message": "重复投递"},
        )
        recorder.observe(replay)
        env["db"].expunge_all()
        after = len(_events(env["db"], run.run_id))
        assert after == before, "重复 (run_id, seq) 不应新增事件行"
        # 终态未被破坏（run_completed 仍唯一且状态不变）
        assert _successful_run(env["db"]).status == "succeeded"

    def test_conversation_delete_cascades(self, record_env) -> None:
        """E1/FR-002：级联删除声明正确——连接级开启外键后删会话清空三表。"""
        from sqlalchemy import text as sql_text

        env = record_env
        env["fake"].script(ContentDelta(text="回答"))
        reply_id = _send(env["client"], env["conversation"].id, "你好").json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _successful_run(env["db"])
        assert _events(env["db"], run.run_id)
        assert _payloads(env["db"], run.run_id)
        # StaticPool 单连接：对该连接开启 PRAGMA 后，同一会话请求的删除同样受约束
        env["db"].execute(sql_text("PRAGMA foreign_keys=ON"))
        conversation = env["db"].get(ConversationEntry, env["conversation"].id)
        env["db"].delete(conversation)
        env["db"].commit()
        env["db"].expunge_all()
        assert env["db"].query(RunEntry).count() == 0
        assert env["db"].query(RunEventEntry).count() == 0
        assert env["db"].query(RunPayloadEntry).count() == 0


class TestBackgroundRun:
    def test_disconnect_midrun_continues(self, record_env) -> None:
        """E2/FR-006：无活跃订阅（客户端断开/未订阅等价）→ 任务后台继续、终态照常落库。

        011 起 build_message_stream 的断开取消逻辑已移除（契约 runtime-events-011.md
        §4）；本测试验证"整个生命周期无订阅者"这一后台运行的极限情形。
        """
        env = record_env
        env["fake"].script(ContentDelta(text="后台完成的内容"), BLOCK)
        reply_id = _send(env["client"], env["conversation"].id, "长任务").json()["reply_message_id"]
        # 不订阅：等待任务进入阻塞态后解除阻塞，任务在"无任何 SSE 连接"下完成
        deadline = time.time() + 2
        while time.time() < deadline and not env["fake"].calls:
            time.sleep(0.01)
        env["fake"].unblocked = True
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _successful_run(env["db"])
        assert run.status == "succeeded"
        reply = env["db"].get(MessageEntry, reply_id)
        assert reply.status == "completed"
        assert reply.content == "后台完成的内容"
        # 事后订阅：任务已终结 → 立即收到终态 done（幂等订阅语义）
        events = read_sse(env["client"], env["conversation"].id, reply_id)
        assert events[-1][0] == "run_completed"
        assert events[-1][1]["message"]["content"] == "后台完成的内容"

    def test_max_rounds_partial(self, record_env, monkeypatch) -> None:
        """E3/SC-001：轮数耗尽且仍请求工具 → 收尾作答、状态 partial。"""
        from app.models import RunEntry as _R

        env = record_env
        env["db"].refresh(env["agent"])
        env["agent"].max_rounds = 2
        env["db"].commit()
        stream = _use_rounds(monkeypatch, RoundsStream())
        stream.script_rounds([
            ToolCallDelta(index=0, id="t1", name="current_time", arguments_fragment="{}"),
        ])
        reply_id = _send(env["client"], env["conversation"].id, "几点了").json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _runs(env["db"])[-1]
        assert run.status == "partial"
        assert "轮数" in run.end_reason

    def test_tool_execution_failure_then_succeed(self, record_env, monkeypatch) -> None:
        """E3/SC-001：工具执行失败（execution_error）→ 错误交还模型后继续完成。"""
        from app.models import AgentBinding, ToolEntry

        env = record_env
        env["db"].refresh(env["agent"])
        shell = env["db"].query(ToolEntry).filter(ToolEntry.name == "shell").one()
        env["db"].add(AgentBinding(
            agent_id=env["agent"].id, resource_type="tool", resource_id=shell.id,
        ))
        env["db"].commit()
        stream = _use_rounds(monkeypatch, RoundsStream())
        stream.script_rounds(
            [ToolCallDelta(index=0, id="t1", name="shell",
                           arguments_fragment='{"command": "exit 3"}')],
            [ContentDelta(text="已忽略失败结果，直接回答")],
        )
        reply_id = _send(env["client"], env["conversation"].id, "跑个命令").json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _successful_run(env["db"])
        # 执行入口口径：执行失败计入 tool_call_count（denied 才不计）
        assert run.tool_call_count == 1
        failed = [e for e in _events(env["db"], run.run_id)
                  if e.event_type == "tool_call_completed" and e.data.get("status") == "error"]
        assert failed, "应有执行失败的工具事件"
        # 模型继续完成，运行成功
        assert run.status == "succeeded"


class TestRunReplay:
    def test_replay_rebuilds_segments(self, record_env, monkeypatch) -> None:
        """优化①：刷新后回显——回放接口还原思考/正文/工具卡片交错序与完整文本。"""
        env = record_env
        stream = _use_rounds(monkeypatch, RoundsStream())
        stream.script_rounds(
            [
                ReasoningDelta(text="先想 "),
                ContentDelta(text="查询中，"),
                ToolCallDelta(index=0, id="c9", name="current_time", arguments_fragment="{}"),
            ],
            [ContentDelta(text="现在是 12:00")],
        )
        reply_id = _send(env["client"], env["conversation"].id, "几点").json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        resp = env["client"].get(f"/api/conversations/{env['conversation'].id}/run-replays")
        assert resp.status_code == 200
        replays = resp.json()
        assert len(replays) == 1
        replay = replays[0]
        assert replay["reply_message_id"] == reply_id
        kinds = [item["kind"] for item in replay["items"]]
        # 交错序：轮1思考→轮1正文→工具卡片→轮2正文
        assert kinds == ["reasoning", "content", "tool", "content"]
        tool_item = replay["items"][2]
        assert tool_item["callId"]
        assert tool_item["displayName"]
        assert tool_item["paramsText"]
        assert tool_item["resultText"]
        assert replay["items"][3]["text"] == "现在是 12:00"

    def test_replay_empty_for_fresh_conversation(self, record_env) -> None:
        env = record_env
        resp = env["client"].get(f"/api/conversations/{env['conversation'].id}/run-replays")
        assert resp.status_code == 200
        assert resp.json() == []

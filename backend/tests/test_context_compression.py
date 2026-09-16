"""上下文自动压缩测试（specs/011 FR-022~042；US4/US5/US6）。"""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    AgentEntry,
    ConversationCompactionEntry,
    MessageEntry,
    RunEntry,
    RunEventEntry,
)
from app.services.generation_registry import get_registry
from app.services.openai_client import ContentDelta
from fastapi.testclient import TestClient

from tests.conftest import BLOCK, FakeStream
from tests.test_chat_stream import read_sse, wait_terminal
from tests.test_run_records import RoundsStream, _use_rounds

LONG = "x" * 1000  # ≈604 tokens/条（600 + 4 开销）


@pytest.fixture
def compact_env(
    client: TestClient,
    db_session: Session,
    seed_model,
    seed_agent: AgentEntry,
    fake_stream: FakeStream,
    chat_session_factory,
    runtime_db,
    recorder_db,
    tools_seeded,
    clean_registry,
):
    """压缩测试环境：会话 + 可直接播种历史的消息工具。"""

    def seed_history(pairs: int, content_len: int = 1000) -> None:
        seq = 1
        for i in range(pairs):
            db_session.add(MessageEntry(
                conversation_id=conversation.id, role="user",
                content="q" * content_len, status="completed", seq=seq,
            ))
            db_session.add(MessageEntry(
                conversation_id=conversation.id, role="assistant",
                agent_id=seed_agent.id, agent_name=seed_agent.name,
                content="a" * content_len, status="completed", seq=seq + 1,
            ))
            seq += 2
        db_session.commit()

    from app.models import ConversationEntry
    conversation = ConversationEntry(title="压缩会话", agent_id=seed_agent.id)
    db_session.add(conversation)
    db_session.commit()

    return {
        "client": client, "db": db_session,
        "agent": seed_agent, "model": seed_model,
        "conversation": conversation, "fake": fake_stream,
        "seed_history": seed_history,
    }


def _send(client, cid, content):
    return client.post(f"/api/conversations/{cid}/messages", json={"content": content})


def _run_row(db: Session) -> RunEntry:
    rows = list(db.query(RunEntry).all())
    assert rows, "没有运行记录"
    return rows[-1]


def _events(db: Session, run_id: str) -> list[RunEventEntry]:
    return list(
        db.query(RunEventEntry)
        .filter(RunEventEntry.run_id == run_id)
        .order_by(RunEventEntry.seq)
        .all()
    )


class TestAutoCompact:
    def test_threshold_trigger_and_persist(self, compact_env) -> None:
        """US4①：估算达阈值触发压缩；摘要与边界落库；原文保留；压缩请求计入统计。"""
        env = compact_env
        env["seed_history"](pairs=6)  # ≈7248 tokens 估算 > 阈值 2549
        env["fake"].script(ContentDelta(text="压缩摘要回答"))
        response = _send(env["client"], env["conversation"].id, "新问题")
        assert response.status_code == 201
        reply_id = response.json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _run_row(env["db"])
        assert run.status == "succeeded"
        events = _events(env["db"], run.run_id)
        # 压缩请求（含分批）+ 聊天请求都计入模型调用（FR-045）
        completed = next(e for e in events if e.event_type == "compression_completed")
        assert run.model_call_count == completed.data["batches"] + 1
        names = [e.event_type for e in events]
        assert "compression_started" in names
        assert "compression_completed" in names
        comp = next(e for e in events if e.event_type == "compression_started")
        assert comp.data["trigger_reason"] in ("threshold", "precheck")
        assert comp.data["estimated_input_tokens"] > 0
        completed = next(e for e in events if e.event_type == "compression_completed")
        assert completed.data["boundary_seq"] > 0
        assert completed.data["groups_compressed"] > 0
        # 摘要与边界落库（FR-033）
        row = env["db"].query(ConversationCompactionEntry).filter_by(
            conversation_id=env["conversation"].id).one()
        assert row.summary_text == "压缩摘要回答"
        assert row.boundary_seq > 0
        # 原始消息无删改（FR-035）
        count = env["db"].query(MessageEntry).filter_by(
            conversation_id=env["conversation"].id).count()
        assert count == 12 + 2  # 6 对历史 + 本次 user + 占位回复

    def test_second_compaction_incremental(self, compact_env) -> None:
        """US4③：再次压缩以前版摘要为基础，边界单调推进。"""
        env = compact_env
        env["seed_history"](pairs=6)
        env["fake"].script(ContentDelta(text="第一版摘要"))
        reply_id = _send(env["client"], env["conversation"].id, "问题一").json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        first = env["db"].query(ConversationCompactionEntry).one()
        first_boundary = first.boundary_seq
        # 新增历史后再次触发
        env["fake"].script(ContentDelta(text="第二版摘要"))
        reply_id2 = _send(env["client"], env["conversation"].id, "问题二").json()["reply_message_id"]
        wait_terminal(reply_id2)
        env["db"].expunge_all()
        second = env["db"].query(ConversationCompactionEntry).one()
        run2 = _run_row(env["db"])
        assert second.boundary_seq > first_boundary
        assert second.summary_text == "第二版摘要"


class TestCompactDisabled:
    def test_disabled_no_summary_and_422(self, compact_env) -> None:
        """US5：关闭自动压缩——超容量发送 422 明确提示，无摘要请求（FR-027）。"""
        env = compact_env
        env["db"].refresh(env["agent"])
        env["agent"].auto_compact = False
        env["db"].commit()
        env["seed_history"](pairs=6)
        env["fake"].script(ContentDelta(text="不应到达"))
        response = _send(env["client"], env["conversation"].id, "新问题")
        assert response.status_code == 422
        assert "开启自动压缩" in response.json()["detail"]
        # 未产生运行与摘要请求
        assert env["db"].query(RunEntry).count() == 0
        assert all("压缩" not in (c.get("messages") or [{}])[0].get("content", "")
                   for c in env["fake"].calls) if env["fake"].calls else True

    def test_fixed_content_overflow_422(self, compact_env) -> None:
        """US5/FR-039：固定内容本身超容量 → 发送即 422，不发出必超限请求。"""
        env = compact_env
        env["db"].refresh(env["agent"])
        env["agent"].system_prompt = "S" * 6000  # ≈3600 tokens > 可用 3187
        env["db"].commit()
        response = _send(env["client"], env["conversation"].id, "你好")
        assert response.status_code == 422
        assert env["db"].query(RunEntry).count() == 0


class TestCompactFailure:
    def test_summary_failure_falls_back(self, compact_env, monkeypatch) -> None:
        """US6：摘要失败 → compression_failed + fallback；边界与历史不变（FR-040/041）。"""
        env = compact_env
        env["seed_history"](pairs=6)
        stream = _use_rounds(monkeypatch, RoundsStream())
        stream.script_rounds(
            [RuntimeError("summary boom")],  # 压缩摘要请求失败
            [ContentDelta(text="降级后回答")],  # 裁剪后聊天请求
        )
        reply_id = _send(env["client"], env["conversation"].id, "新问题").json()["reply_message_id"]
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _run_row(env["db"])
        assert run.status == "succeeded"
        names = [e.event_type for e in _events(env["db"], run.run_id)]
        assert "compression_failed" in names
        assert "compression_fallback" in names
        # 备用裁剪不写库：无压缩状态行（FR-041）
        assert env["db"].query(ConversationCompactionEntry).count() == 0
        # 原始历史完整保留
        count = env["db"].query(MessageEntry).filter_by(
            conversation_id=env["conversation"].id).count()
        assert count == 14

    def test_cancel_during_compaction(self, compact_env) -> None:
        """US6：压缩过程中取消 → 运行 cancelled、压缩请求终止（FR-042）。"""
        env = compact_env
        env["seed_history"](pairs=6)
        env["fake"].script(ContentDelta(text="缓慢摘要"), BLOCK)
        reply_id = _send(env["client"], env["conversation"].id, "新问题").json()["reply_message_id"]
        deadline = time.time() + 2
        while time.time() < deadline and len(env["fake"].calls) < 1:
            time.sleep(0.01)
        stop = env["client"].post(
            f"/api/conversations/{env['conversation'].id}/messages/{reply_id}/stop")
        assert stop.status_code == 200
        wait_terminal(reply_id)
        env["db"].expunge_all()
        run = _run_row(env["db"])
        assert run.status == "cancelled"
        # 压缩未成功：无压缩状态写回
        assert env["db"].query(ConversationCompactionEntry).count() == 0

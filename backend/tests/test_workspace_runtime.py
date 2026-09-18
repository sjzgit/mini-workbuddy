"""Runtime 集成测试：工作空间权限全链路（specs/014-workspace-permission，US2/US3/US4/US5）。

复用 009 测试脚手架（FakeRuntimeStream 多轮剧本 / runtime_db / collect_events 先例
test_agent_runtime.py）：授权内放行、范围外 ASK_USER 挂起 → 允许（grant 生效）/
拒绝（denied 不中断）、保护路径直接 DENY、临时授权不跨运行、快照不受运行中切换
影响、permission_checked 事件产出与落库。
"""

import asyncio
from pathlib import Path

import pytest

from app.models import ConversationEntry
from app.services.agent_runtime import (
    RunHistoryMessage,
    RunLimits,
    RunRequest,
    execute_run,
)
from app.services.agent_runtime import ask_user as ask_registry
from app.core.config import settings
from test_agent_runtime_fixtures import (
    content_round,
    tool_call_round,
)

# 复用 009 假流与 DB 夹具（import 先例：test_agent_runtime.py 导入 fixtures 模块）
from test_agent_runtime_fixtures import (  # noqa: F401
    collect_events,
    fake_runtime_stream,
    runtime_db,
)


def _make_conversation(db_session, seed_agent, workspace: str | None) -> ConversationEntry:
    entry = ConversationEntry(title="014 runtime", agent_id=seed_agent.id)
    if workspace is not None:
        entry.workspace_path = workspace
        entry.workspace_source = "user_selected"
    db_session.add(entry)
    db_session.commit()
    return entry


def _request(conversation_id: int, agent_id: int) -> RunRequest:
    return RunRequest(
        agent_id=agent_id,
        user_message="test",
        history=[RunHistoryMessage(role="user", content="test", seq=1)],
        limits=RunLimits(),
        conversation_id=conversation_id,
        reply_message_id=999001,  # 非空 = 聊天在场（挂起机制可用）
    )


def _bind_tool(db_session, seed_agent, name: str) -> None:
    from test_agent_runtime_fixtures import bind

    from app.models import ToolEntry

    tool = db_session.query(ToolEntry).filter(ToolEntry.name == name).first()
    bind(db_session, seed_agent.id, "tool", tool.id)


def _find(events, name):
    return [e for e in events if e.event == name]


async def _drain_with_answer(request: RunRequest, answer: str | None, timeout: float = 10):
    """消费事件流；出现 ask_user 时以给定答案自动应答（模拟用户回答端点）。"""
    async def _inner():
        events = []
        async for event in execute_run(request):
            events.append(event)
            if event.event == "ask_user" and answer is not None:
                assert ask_registry.submit_answer(event.data["call_id"], [answer], None)
            if event.event == "run_completed":
                break
        return events

    return await asyncio.wait_for(_inner(), timeout=timeout)


@pytest.fixture
def ws_workspace_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离的系统授权目录（settings.authorized_dir）。"""
    root = tmp_path / "sysws"
    root.mkdir()
    monkeypatch.setattr(settings, "authorized_dir", str(root))
    return root


# runtime 权限上下文构造在 run_agent_loop ① 阶段：导入 settings.authorized_dir 的
# 是 permission 模块内部（函数内引用），monkeypatch settings 属性即可生效


class TestWorkspaceAllow:
    def test_file_inside_system_workspace_direct_success(
        self, db_session, runtime_db, recorder_db, ws_workspace_dir, fake_runtime_stream,
        seed_agent, tools_seeded,
    ) -> None:
        _bind_tool(db_session, seed_agent, "file_read_write")
        (ws_workspace_dir / "hello.txt").write_text("内容", encoding="utf-8")
        conversation = _make_conversation(db_session, seed_agent, None)
        fake_runtime_stream.script(
            tool_call_round("file_read_write", '{"action": "read", "path": "hello.txt"}'),
            content_round("读取完成"),
        )

        events = asyncio.run(collect_events(_request(conversation.id, seed_agent.id)))
        completed = events[-1]
        assert completed.event == "run_completed"
        assert completed.data["status"] == "completed"
        tool_done = _find(events, "tool_call_completed")
        assert tool_done and tool_done[0].data["status"] == "success"
        # US5：allow 决策事件已产出
        checked = _find(events, "permission_checked")
        assert checked and checked[0].data["decision"] == "allow"

    def test_file_in_session_workspace_allows(
        self, db_session, runtime_db, recorder_db, ws_workspace_dir, fake_runtime_stream,
        seed_agent, tools_seeded, tmp_path: Path,
    ) -> None:
        _bind_tool(db_session, seed_agent, "file_read_write")
        session_ws = tmp_path / "proj"
        session_ws.mkdir()
        (session_ws / "note.txt").write_text("x", encoding="utf-8")
        conversation = _make_conversation(db_session, seed_agent, str(session_ws))
        fake_runtime_stream.script(
            tool_call_round(
                "file_read_write",
                '{"action": "read", "path": "%s"}' % (session_ws / "note.txt").as_posix(),
            ),
            content_round("ok"),
        )

        events = asyncio.run(collect_events(_request(conversation.id, seed_agent.id)))
        tool_done = _find(events, "tool_call_completed")
        assert tool_done and tool_done[0].data["status"] == "success"

    def test_shell_runs_with_workspace_cwd(
        self, db_session, runtime_db, recorder_db, ws_workspace_dir, fake_runtime_stream,
        seed_agent, tools_seeded, tmp_path: Path,
    ) -> None:
        _bind_tool(db_session, seed_agent, "shell")
        session_ws = tmp_path / "proj"
        session_ws.mkdir()
        conversation = _make_conversation(db_session, seed_agent, str(session_ws))
        fake_runtime_stream.script(
            tool_call_round("shell", '{"command": "cd"}'),
            content_round("ok"),
        )

        events = asyncio.run(collect_events(_request(conversation.id, seed_agent.id)))
        tool_done = _find(events, "tool_call_completed")
        # cd 无参数 = 输出当前目录：成功即证明执行基准目录可用（Windows cd 打印 cwd）
        assert tool_done and tool_done[0].data["status"] == "success"


class TestPermissionAsk:
    def test_outside_path_triggers_ask_and_allow_grants(
        self, db_session, runtime_db, recorder_db, ws_workspace_dir, fake_runtime_stream,
        seed_agent, tools_seeded, tmp_path: Path,
    ) -> None:
        _bind_tool(db_session, seed_agent, "file_read_write")
        outside = tmp_path / "outside.txt"
        outside.write_text("外部内容", encoding="utf-8")
        conversation = _make_conversation(db_session, seed_agent, None)
        fake_runtime_stream.script(
            tool_call_round(
                "file_read_write",
                '{"action": "read", "path": "%s"}' % outside.as_posix(),
            ),
            content_round("ok"),
        )

        events = asyncio.run(_drain_with_answer(
            _request(conversation.id, seed_agent.id), "允许本次访问",
        ))
        ask_events = _find(events, "ask_user")
        assert ask_events, "范围外路径必须挂起询问"
        assert "允许本次访问" in ask_events[0].data["options"]
        assert str(outside.resolve()) in ask_events[0].data["question"]
        tool_done = _find(events, "tool_call_completed")
        assert tool_done and tool_done[0].data["status"] == "success"

    def test_reject_denies_tool_but_run_continues(
        self, db_session, runtime_db, recorder_db, ws_workspace_dir, fake_runtime_stream,
        seed_agent, tools_seeded, tmp_path: Path,
    ) -> None:
        _bind_tool(db_session, seed_agent, "file_read_write")
        outside = tmp_path / "outside.txt"
        outside.write_text("x", encoding="utf-8")
        conversation = _make_conversation(db_session, seed_agent, None)
        fake_runtime_stream.script(
            tool_call_round(
                "file_read_write",
                '{"action": "read", "path": "%s"}' % outside.as_posix(),
            ),
            content_round("已收到拒绝，改用其他方式"),
        )

        events = asyncio.run(_drain_with_answer(
            _request(conversation.id, seed_agent.id), "拒绝",
        ))
        tool_done = _find(events, "tool_call_completed")
        assert tool_done and tool_done[0].data["status"] == "denied"
        assert "permission_denied_by_user" in tool_done[0].data["result"]
        completed = events[-1]
        assert completed.event == "run_completed"
        assert completed.data["status"] == "completed"  # 运行继续（FR-026）

    def test_protected_path_denied_without_ask(
        self, db_session, runtime_db, recorder_db, ws_workspace_dir, fake_runtime_stream,
        seed_agent, tools_seeded,
    ) -> None:
        _bind_tool(db_session, seed_agent, "file_read_write")
        conversation = _make_conversation(db_session, seed_agent, None)
        fake_runtime_stream.script(
            tool_call_round(
                "file_read_write", '{"action": "read", "path": "C:/Windows/win.ini"}',
            ),
            content_round("ok"),
        )

        events = asyncio.run(collect_events(_request(conversation.id, seed_agent.id)))
        assert not _find(events, "ask_user"), "保护路径不得进入确认流程（Invariant 8）"
        tool_done = _find(events, "tool_call_completed")
        assert tool_done and tool_done[0].data["status"] == "denied"
        assert "system_protected_path" in tool_done[0].data["result"]

    def test_grant_does_not_leak_to_next_run(
        self, db_session, runtime_db, recorder_db, ws_workspace_dir, fake_runtime_stream,
        seed_agent, tools_seeded, tmp_path: Path,
    ) -> None:
        _bind_tool(db_session, seed_agent, "file_read_write")
        outside = tmp_path / "outside.txt"
        outside.write_text("x", encoding="utf-8")
        conversation = _make_conversation(db_session, seed_agent, None)
        arguments = '{"action": "read", "path": "%s"}' % outside.as_posix()

        # 运行 1：允许 → grant 生效
        fake_runtime_stream.script(
            tool_call_round("file_read_write", arguments),
            content_round("ok"),
        )
        events1 = asyncio.run(_drain_with_answer(
            _request(conversation.id, seed_agent.id), "允许本次访问",
        ))
        tool_done = _find(events1, "tool_call_completed")
        assert tool_done and tool_done[0].data["status"] == "success"

        # 运行 2：新运行不继承 grant → 必须再次询问（FR-023 / Invariant 5）
        fake_runtime_stream.script(
            tool_call_round("file_read_write", arguments),
            content_round("ok"),
        )
        events2 = asyncio.run(_drain_with_answer(
            _request(conversation.id, seed_agent.id), "拒绝",
        ))
        assert _find(events2, "ask_user"), "新运行必须重新确认（grant 不跨运行）"


class TestSnapshot:
    def test_run_started_carries_workspace_snapshot(
        self, db_session, runtime_db, recorder_db, ws_workspace_dir, fake_runtime_stream,
        seed_agent, tools_seeded, tmp_path: Path,
    ) -> None:
        session_ws = tmp_path / "proj"
        session_ws.mkdir()
        conversation = _make_conversation(db_session, seed_agent, str(session_ws))
        fake_runtime_stream.script(content_round("done"))

        events = asyncio.run(collect_events(_request(conversation.id, seed_agent.id)))
        started = _find(events, "run_started")[0]
        assert started.data.get("workspace_path") == str(session_ws.resolve())

    def test_runs_row_records_workspace(
        self, db_session, runtime_db, recorder_db, ws_workspace_dir, fake_runtime_stream,
        seed_agent, tools_seeded, tmp_path: Path,
    ) -> None:
        from sqlalchemy import select

        from app.models import RunEntry

        session_ws = tmp_path / "proj"
        session_ws.mkdir()
        conversation = _make_conversation(db_session, seed_agent, str(session_ws))
        fake_runtime_stream.script(content_round("done"))

        asyncio.run(collect_events(_request(conversation.id, seed_agent.id)))
        with runtime_db() as session:
            row = session.scalar(
                select(RunEntry).where(RunEntry.conversation_id == conversation.id),
            )
            assert row is not None
            assert row.workspace_path == str(session_ws.resolve())


class TestPermissionEvents:
    def test_allow_event_persisted_to_run_events(
        self, db_session, runtime_db, recorder_db, ws_workspace_dir, fake_runtime_stream,
        seed_agent, tools_seeded,
    ) -> None:
        from sqlalchemy import select

        from app.models import RunEventEntry

        _bind_tool(db_session, seed_agent, "file_read_write")
        (ws_workspace_dir / "f.txt").write_text("x", encoding="utf-8")
        conversation = _make_conversation(db_session, seed_agent, None)
        fake_runtime_stream.script(
            tool_call_round("file_read_write", '{"action": "read", "path": "f.txt"}'),
            content_round("ok"),
        )

        events = asyncio.run(collect_events(_request(conversation.id, seed_agent.id)))
        checked = _find(events, "permission_checked")
        assert checked, "allow 判定也必须发审计事件（SC-008）"
        payload = checked[0].data
        assert payload["decision"] == "allow"
        for key in ("tool_name", "path", "reason"):
            assert key in payload

        with runtime_db() as session:
            rows = session.scalars(
                select(RunEventEntry).where(
                    RunEventEntry.event_type == "permission_checked",
                ),
            ).all()
            assert rows, "permission_checked 必须落 run_events（US5）"
            assert rows[0].data["decision"] == "allow"

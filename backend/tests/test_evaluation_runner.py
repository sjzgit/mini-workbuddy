"""评测执行引擎测试（specs/012 US3，FR-009~022 / Invariants 1-12）。

注入假 execute_run 事件流（monkeypatch runner 命名空间），评测不需要真实 LLM。
"""

import asyncio

import pytest
from sqlalchemy import select

from app.models import EvaluationCaseRunEntry, EvaluationRunEntry, RunEntry
from app.schemas.agent_runtime import RunCompletedData
from app.services.agent_runtime import RunRequest
from app.services.evaluation import dataset_service, runner, task_service


class FakeExecuteRun:
    """脚本化 execute_run 替身：每次调用弹出一个事件序列。"""

    def __init__(self) -> None:
        self.scripts: list[list] = []
        self.calls: list[RunRequest] = []

    def script(self, *sequences: list) -> None:
        self.scripts = list(sequences)

    async def __call__(self, request: RunRequest):
        self.calls.append(request)
        for event in self.scripts.pop(0) if self.scripts else []:
            yield event


def completed_event(
    content: str, *, status: str = "completed",
    prompt=10, completion=5, total=15,
) -> object:
    """构造 run_completed 事件（真实事件对象，data dict 与契约一致）。"""
    from app.services.agent_runtime.events import RunEventEmitter

    emitter = RunEventEmitter("fake")
    event = emitter.emit(
        "run_completed",
        RunCompletedData(
            status=status, reason="模型直接给出回答，运行正常结束",
            content_text=content,
            usage_total={"prompt_tokens": prompt, "completion_tokens": completion,
                         "total_tokens": total},
        ),
        round=0,
    )
    return event


@pytest.fixture
def fake_execute_run(monkeypatch: pytest.MonkeyPatch) -> FakeExecuteRun:
    fake = FakeExecuteRun()
    monkeypatch.setattr(runner, "execute_run", fake)
    return fake


@pytest.fixture
def eval_env(
    db_session, monkeypatch: pytest.MonkeyPatch, seed_agent,
):
    """评测执行环境：测试库绑定 + 数据集/任务/Run/CaseRun 就绪。"""
    factory = sessionmaker_like(db_session)
    monkeypatch.setattr(runner, "SessionLocal", factory)
    monkeypatch.setattr(runner, "_SL", factory, raising=False)

    ds = dataset_service.create_dataset(db_session, "评测集", "")
    dataset_service.import_cases(db_session, ds.id, {
        "name": "x", "cases": [
            {"user_question": "q1", "expected_answer": "回答A", "scoring_criteria": None},
            {"user_question": "q2", "expected_answer": None,
             "scoring_criteria": "要提到退款"},
            {"user_question": "q3", "expected_answer": "x", "scoring_criteria": None},
            {"user_question": "q4", "expected_answer": None, "scoring_criteria": None},
        ],
    })
    task = task_service.create_task(
        db_session, "评测任务", seed_agent.id, ds.id, "exact_match", {}, 80,
    )
    return {"task": task, "dataset": ds, "agent": seed_agent}


def sessionmaker_like(db_session):
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)


async def _drive(run_pk: int, control=None) -> None:
    """驱动后台主循环至完成（直接 await 内部协程，无需真 create_task）。"""
    if control is None:
        control = runner.EvaluationRunControl(run_pk=run_pk)
    await runner._run_evaluation_loop(control)


class TestBasicExecution:
    def test_run_and_aggregation(self, db_session, eval_env, fake_execute_run):
        """全链路：通过/执行失败/评 0/空回答 → 聚合正确（Invariant 8/9）。"""
        run = _create_run(db_session, eval_env)
        fake_execute_run.script(
            [completed_event("回答A")],                    # q1 → passed 100
            [completed_event("模型挂了", status="error")],  # q2 → execution_failed
            [completed_event("完全不同的回答")],             # q3 → failed 0
            [completed_event("   ")],                       # q4 空回答 → execution_failed
        )
        asyncio.run(_drive(run.id))
        updated = db_session.get(EvaluationRunEntry, run.id)
        assert updated.status == "completed"
        assert updated.passed_cases == 1
        assert updated.failed_cases == 1
        assert updated.execution_failed_cases == 2
        assert updated.judge_failed_cases == 0
        # 平均分只算有效评分：(100 + 0) / 2 = 50；失败不判 0 分
        assert updated.average_score == 50
        assert updated.pass_rate == 50
        crs = db_session.scalars(
            select(EvaluationCaseRunEntry)
            .where(EvaluationCaseRunEntry.evaluation_run_id == run.id)
        ).all()
        exec_failed = [c for c in crs if c.status == "execution_failed"]
        assert len(exec_failed) == 2
        assert all(c.score is None for c in exec_failed)
        assert all(c.error_type for c in exec_failed)
        # 通过的 Case 记录分数/理由/评分器与 AgentRun 关联
        passed = next(c for c in crs if c.status == "passed")
        assert passed.score == 100
        assert passed.reason == "答案完全匹配"
        assert passed.evaluator_type == "exact_match"
        assert passed.agent_run_id
        assert passed.total_tokens == 15

    def test_independent_context(self, db_session, eval_env, fake_execute_run):
        """每 Case 独立上下文：history 空、无会话、user_message=问题（Invariant 3）。"""
        run = _create_run(db_session, eval_env)
        fake_execute_run.script(*[
            [completed_event(f"回答{i}")] for i in range(4)
        ])
        asyncio.run(_drive(run.id))
        assert len(fake_execute_run.calls) == 4
        for call in fake_execute_run.calls:
            assert call.history == []
            assert call.conversation_id is None
            assert call.user_message in {"q1", "q2", "q3", "q4"}
            assert call.run_id  # agent_run_id 已生成

    def test_single_script_exhausted(self, db_session, eval_env, fake_execute_run):
        """剧本耗尽（空事件流）→ 终态 error → execution_failed，不判 0 分。"""
        run = _create_run(db_session, eval_env)
        fake_execute_run.script([completed_event("回答A")])
        asyncio.run(_drive(run.id))
        updated = db_session.get(EvaluationRunEntry, run.id)
        assert updated.status == "completed"
        assert updated.passed_cases == 1
        assert updated.execution_failed_cases == 3


def _create_run(db_session, env):
    from app.services.evaluation import run_service as eval_run_service

    return eval_run_service.create_run_for_task(db_session, env["task"].id)


class TestAsyncRouteScheduling:
    """回归：async 路由在事件循环内 create_task，后台评测推进至终态。

    BUG 背景（012 修复记录）：start_run 曾为同步 def → AnyIO 工作线程无
    事件循环 → create_task 未调度 → CaseRun 永远 pending。
    """

    def test_start_run_drives_background_loop(
        self, db_session, eval_env, fake_execute_run, monkeypatch,
    ):
        import time

        from fastapi.testclient import TestClient

        from app.core.db import get_session
        from app.main import app

        fake_execute_run.script(
            *[[completed_event(f"回答{i}")] for i in range(4)]
        )
        app.dependency_overrides[get_session] = lambda: db_session
        try:
            client = TestClient(app)
            r = client.post(f"/api/evaluation/tasks/{eval_env['task'].id}/runs")
            assert r.status_code == 202, r.text
            run_id = r.json()["id"]

            deadline = time.time() + 10
            status = "pending"
            while time.time() < deadline:
                status = client.get(f"/api/evaluation/runs/{run_id}").json()["status"]
                if status not in ("pending", "running"):
                    break
                time.sleep(0.05)
        finally:
            app.dependency_overrides.pop(get_session, None)

        assert status == "completed"
        db_session.expire_all()  # 后台任务独立会话写库：失效本地缓存再断言
        rows = db_session.scalars(
            select(EvaluationCaseRunEntry)
            .where(EvaluationCaseRunEntry.evaluation_run_id == run_id)
        ).all()
        print("case statuses:", [(r.dataset_case_id, r.status) for r in rows])
        assert len(rows) == 4
        # 核心断言：后台主循环被调度并推进全部 CaseRun 到终态（不再 pending），
        # 且评分器真实介入（exec_failed 才代表执行层失败）
        assert all(row.status != "pending" for row in rows)
        assert all(
            row.status in ("passed", "failed", "judge_failed", "execution_failed")
            for row in rows
        )
        # 控制柄已随任务完成清理
        assert run_id not in runner.RUN_CONTROLS

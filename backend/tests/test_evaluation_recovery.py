"""聚合口径 / 重启恢复 / 运行控制测试（specs/012 US4/US5，FR-020/023~027）。"""

import asyncio

import pytest
from sqlalchemy import select

from app.models import EvaluationCaseRunEntry, EvaluationRunEntry
from app.services.evaluation import dataset_service, runner, task_service
from app.services.evaluation import run_service as eval_run_service

from tests.test_evaluation_runner import (
    FakeExecuteRun,
    completed_event,
    _drive,
)


@pytest.fixture
def eval_env2(db_session, monkeypatch, seed_agent):
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False,
    )
    monkeypatch.setattr(runner, "SessionLocal", factory)

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
    return {"task": task, "agent": seed_agent}


def _make_run(db_session, env):
    return eval_run_service.create_run_for_task(db_session, env["task"].id)


class TestAggregation:
    def test_all_judge_failed_average_none(self, db_session, eval_env2, monkeypatch):
        """全失败：average_score/pass_rate = NULL（非 0，FR-020）。"""
        run = _make_run(db_session, eval_env2)
        fake = FakeExecuteRun()
        monkeypatch.setattr(runner, "execute_run", fake)
        fake.script(*[[completed_event("x", status="error")] for _ in range(4)])
        asyncio.run(_drive(run.id))
        updated = db_session.get(EvaluationRunEntry, run.id)
        assert updated.execution_failed_cases == 4
        assert updated.average_score is None
        assert updated.pass_rate is None
        # token 是"已知值之和"口径：执行失败也可能有 usage（15*4=60）
        assert updated.total_tokens == 60

    def test_aggregate_ignores_cancelled(self, db_session, eval_env2):
        """重试场景聚合：每 Case 取最新非取消 CaseRun（FR-025/Invariant 12）。"""
        run = _make_run(db_session, eval_env2)
        rows = [
            EvaluationCaseRunEntry(evaluation_run_id=run.id, dataset_case_id=1,
                                   status="failed", score=30, attempt=1),
            EvaluationCaseRunEntry(evaluation_run_id=run.id, dataset_case_id=1,
                                   status="passed", score=95, attempt=2),
            EvaluationCaseRunEntry(evaluation_run_id=run.id, dataset_case_id=2,
                                   status="cancelled", attempt=1),
            EvaluationCaseRunEntry(evaluation_run_id=run.id, dataset_case_id=3,
                                   status="failed", score=20, attempt=1),
        ]
        db_session.add_all(rows)
        db_session.commit()
        result = eval_run_service.aggregate_run(db_session, run.id)
        # 有效评分 = [95, 20]：(95+20)/2 = 58；通过率 = 1/2 = 50
        assert result.average_score == 58
        assert result.pass_rate == 50
        # 集合口径：q1(95) + q3(20)；q2 cancelled 不进完成数
        assert result.completed_cases == 2
        assert result.cancelled_cases == 1


class TestRecovery:
    def test_mark_interrupted(self, db_session, eval_env2):
        """RUNNING/PAUSED → INTERRUPTED；未完成 CaseRun → CANCELLED（Invariant 13）。"""
        run_out = _make_run(db_session, eval_env2)
        run = db_session.get(EvaluationRunEntry, run_out.id)
        run.status = "running"
        db_session.commit()
        case_ids = db_session.scalars(
            select(EvaluationCaseRunEntry.id)
            .where(EvaluationCaseRunEntry.evaluation_run_id == run.id)
        ).all()
        db_session.get(EvaluationCaseRunEntry, case_ids[0]).status = "passed"
        db_session.commit()

        count = eval_run_service.mark_interrupted_runs(db_session)
        assert count == 1
        updated = db_session.get(EvaluationRunEntry, run.id)
        assert updated.status == "interrupted"
        assert updated.interrupted_at is not None
        assert updated.interrupted_reason
        cancelled = db_session.scalars(
            select(EvaluationCaseRunEntry)
            .where(EvaluationCaseRunEntry.evaluation_run_id == run.id,
                   EvaluationCaseRunEntry.status == "cancelled")
        ).all()
        assert len(cancelled) == 3
        assert all(c.error_type == "interrupted" for c in cancelled)
        passed = db_session.get(EvaluationCaseRunEntry, case_ids[0])
        assert passed.status == "passed"

    def test_completed_not_interrupted(self, db_session, eval_env2):
        run_out = _make_run(db_session, eval_env2)
        run = db_session.get(EvaluationRunEntry, run_out.id)
        run.status = "completed"
        db_session.commit()
        assert eval_run_service.mark_interrupted_runs(db_session) == 0
        assert db_session.get(EvaluationRunEntry, run.id).status == "completed"


class TestRunControl:
    def test_pause_resume_cancel_flow(self, db_session, eval_env2, monkeypatch):
        """暂停边界 → 恢复续跑（FR-024）。"""
        run = _make_run(db_session, eval_env2)
        control = runner.EvaluationRunControl(run_pk=run.id)
        runner.RUN_CONTROLS[run.id] = control

        fake = FakeExecuteRun()
        monkeypatch.setattr(runner, "execute_run", fake)
        fake.script(
            [completed_event("回答A")],
            [completed_event("回答B")],
            [completed_event("x")],
            [completed_event("y")],
        )
        control.pause_event.set()  # 启动前已暂停：Case 边界即停（0 个执行）

        asyncio.run(runner._run_evaluation_loop(control))
        paused = db_session.get(EvaluationRunEntry, run.id)
        assert paused.status == "paused"
        # 暂停期没有任何 Case 被执行，全部保持 PENDING
        executed = db_session.scalars(
            select(EvaluationCaseRunEntry)
            .where(EvaluationCaseRunEntry.evaluation_run_id == run.id,
                   EvaluationCaseRunEntry.status != "pending")
        ).all()
        assert executed == []

        # 恢复：4 个 Case 均未执行，续跑需 4 份剧本
        fake.script(
            [completed_event("回答A")],
            [completed_event("回答B")],
            [completed_event("x")],
            [completed_event("y")],
        )
        control2 = runner.EvaluationRunControl(run_pk=run.id)
        runner.RUN_CONTROLS[run.id] = control2
        asyncio.run(_drive(run.id))
        db_session.expire_all()  # 后台循环用独立会话写库：先失效本地缓存
        resumed = db_session.get(EvaluationRunEntry, run.id)
        assert resumed.status == "completed"

    def test_cancel_marks_pending_cancelled(self, db_session, eval_env2):
        """取消：剩余 PENDING 全部 CANCELLED，Run → CANCELLED。"""
        run = _make_run(db_session, eval_env2)
        control = runner.EvaluationRunControl(run_pk=run.id)
        control.cancel_event.set()
        runner.RUN_CONTROLS[run.id] = control
        asyncio.run(_drive(run.id, control))
        cancelled_run = db_session.get(EvaluationRunEntry, run.id)
        assert cancelled_run.status == "cancelled"
        rows = db_session.scalars(
            select(EvaluationCaseRunEntry)
            .where(EvaluationCaseRunEntry.evaluation_run_id == run.id)
        ).all()
        assert all(r.status == "cancelled" for r in rows)

    def test_retry_creates_new_case_run(self, db_session, eval_env2):
        """重试：新建 attempt+1 行、原行保留、Run 回 RUNNING 续跑（Invariant 12）。"""
        run = _make_run(db_session, eval_env2)
        target = EvaluationCaseRunEntry(
            evaluation_run_id=run.id, dataset_case_id=1,
            status="execution_failed", error_type="model_error", attempt=1,
        )
        db_session.add(target)
        db_session.commit()
        run_pk, new_pk = runner.retry_case_run(run.id, target.id)
        db_session.expire_all()
        original = db_session.get(EvaluationCaseRunEntry, target.id)
        retry_row = db_session.get(EvaluationCaseRunEntry, new_pk)
        assert original.status == "execution_failed"
        assert retry_row.status == "pending"
        assert retry_row.attempt == 2
        assert retry_row.dataset_case_id == original.dataset_case_id
        assert db_session.get(EvaluationRunEntry, run_pk).status == "running"

    def test_retry_rejects_invalid_target(self, db_session, eval_env2):
        """有效评分（passed）不允许重试；不存在的 CaseRun 404 语义。"""
        run = _make_run(db_session, eval_env2)
        target = EvaluationCaseRunEntry(
            evaluation_run_id=run.id, dataset_case_id=1,
            status="passed", score=100, attempt=1,
        )
        db_session.add(target)
        db_session.commit()
        from app.services.evaluation.run_service import EvaluationNotFoundError

        with pytest.raises(EvaluationNotFoundError):
            runner.retry_case_run(run.id, 99999)
        from app.services.evaluation.runner import EvaluationRunActiveError

        with pytest.raises(EvaluationRunActiveError):
            runner.retry_case_run(run.id, target.id)

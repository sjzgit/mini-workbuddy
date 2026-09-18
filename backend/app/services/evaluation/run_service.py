"""评测运行服务：运行查询、聚合与重启恢复（specs/012，US3/US4）。

契约主定义：specs/012-agent-evaluation/contracts/evaluation-api.md §5
聚合口径（data-model.md §5）：平均分/通过率仅基于"每 Case 最新非取消
CaseRun"中的有效评分（PASSED/FAILED），失败绝不计 0 分（FR-020）。
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    EvaluationCaseRunEntry,
    EvaluationRunEntry,
    EvaluationTaskEntry,
)
from app.schemas.evaluation import (
    CaseRunOut,
    EvaluationRunOut,
    RunListResponse,
    SnapshotCaseOut,
)
from app.services.evaluation import snapshots as snapshot_mod

logger = logging.getLogger(__name__)

RUN_INTERRUPTED_REASON = "评测运行中断：服务在运行期间重启"


class EvaluationNotFoundError(LookupError):
    """评测运行不存在（路由层转 404）。"""


class EvaluationValidationError(ValueError):
    """评测运行业务校验失败（路由层按语义转 409/422）。"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


# ---- 输出映射 ----


def _to_run_out(entry: EvaluationRunEntry) -> EvaluationRunOut:
    """评测运行行 → EvaluationRunOut（契约 §5 EvaluationRunOut）。"""
    return EvaluationRunOut(
        id=entry.id,
        task_id=entry.task_id,
        run_id=entry.run_id, status=entry.status,
        started_at=entry.started_at.isoformat() if entry.started_at else None,
        finished_at=entry.finished_at.isoformat() if entry.finished_at else None,
        interrupted_at=entry.interrupted_at.isoformat() if entry.interrupted_at else None,
        interrupted_reason=entry.interrupted_reason,
        total_cases=entry.total_cases,
        completed_cases=entry.completed_cases,
        passed_cases=entry.passed_cases,
        failed_cases=entry.failed_cases,
        execution_failed_cases=entry.execution_failed_cases,
        judge_failed_cases=entry.judge_failed_cases,
        cancelled_cases=entry.cancelled_cases,
        average_score=entry.average_score,
        pass_rate=entry.pass_rate,
        total_duration_ms=entry.total_duration_ms,
        total_tokens=entry.total_tokens,
        created_at=entry.created_at.isoformat(),
    )


def _to_case_run_out(
    entry: EvaluationCaseRunEntry,
    snapshot_case: dict | None = None,
    case_index: int | None = None,
) -> CaseRunOut:
    """用例运行行 → CaseRunOut（契约 §5 CaseRunOut）。"""
    snap = None
    if snapshot_case is not None:
        snap = SnapshotCaseOut(
            case_id=int(snapshot_case.get("case_id", 0)),
            user_question=str(snapshot_case.get("user_question", "")),
            expected_answer=snapshot_case.get("expected_answer"),
            scoring_criteria=snapshot_case.get("scoring_criteria"),
        )
    return CaseRunOut(
        id=entry.id,
        evaluation_run_id=entry.evaluation_run_id,
        dataset_case_id=entry.dataset_case_id,
        status=entry.status,
        agent_run_id=entry.agent_run_id,
        score=entry.score,
        reason=entry.reason,
        evaluator_type=entry.evaluator_type,
        evaluator_metadata=entry.evaluator_metadata,
        duration_ms=entry.duration_ms,
        input_tokens=entry.input_tokens,
        output_tokens=entry.output_tokens,
        total_tokens=entry.total_tokens,
        tool_call_count=entry.tool_call_count,
        model_call_count=entry.model_call_count,
        iteration_count=entry.iteration_count,
        error_type=entry.error_type,
        error_message=entry.error_message,
        attempt=entry.attempt,
        started_at=entry.started_at.isoformat() if entry.started_at else None,
        finished_at=entry.finished_at.isoformat() if entry.finished_at else None,
        case_index=case_index,
        snapshot_case=snap,
    )


def _get_run(session: Session, run_pk: int) -> EvaluationRunEntry:
    """按主键取 Run；不存在抛 EvaluationNotFoundError（404）。"""
    entry = session.get(EvaluationRunEntry, run_pk)
    if entry is None:
        raise EvaluationNotFoundError(f"评测运行 {run_pk} 不存在")
    return entry


def _snapshot_case_map(task: EvaluationTaskEntry) -> dict[int, dict]:
    """任务 dataset_snapshot.cases → {case_id: case}（数据集被删仍可展示）。"""
    cases = (task.dataset_snapshot or {}).get("cases", [])
    return {
        int(c.get("case_id", 0)): c
        for c in cases if isinstance(c, dict)
    }


def list_runs(
    session: Session,
    *,
    task_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> RunListResponse:
    """运行列表：created_at 倒序、分页、task/status 过滤（契约 §5 GET /runs）。"""
    conditions = []
    if task_id is not None:
        conditions.append(EvaluationRunEntry.task_id == task_id)
    if status:
        conditions.append(EvaluationRunEntry.status == status)
    where = [cond for cond in conditions]
    total = session.scalar(
        select(func.count(EvaluationRunEntry.id)).where(*where)
    )
    entries = session.scalars(
        select(EvaluationRunEntry)
        .where(*where)
        .order_by(EvaluationRunEntry.created_at.desc(), EvaluationRunEntry.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return RunListResponse(
        items=[_to_run_out(entry) for entry in entries],
        total=int(total or 0), page=page, page_size=page_size,
    )


def get_run(session: Session, run_pk: int) -> EvaluationRunOut:
    return _to_run_out(_get_run(session, run_pk))


def get_case_runs(session: Session, run_pk: int) -> list[CaseRunOut]:
    """运行内全部 CaseRun（按 id 升序 = 执行顺序），附快照 Case 与序号。"""
    run = _get_run(session, run_pk)
    task = session.get(EvaluationTaskEntry, run.task_id)
    case_map = _snapshot_case_map(task) if task else {}
    entries = session.scalars(
        select(EvaluationCaseRunEntry)
        .where(EvaluationCaseRunEntry.evaluation_run_id == run_pk)
        .order_by(EvaluationCaseRunEntry.id)
    ).all()
    return [
        _to_case_run_out(
            entry,
            snapshot_case=case_map.get(entry.dataset_case_id),
            case_index=index,
        )
        for index, entry in enumerate(
            session.scalars(
                select(EvaluationCaseRunEntry)
                .where(EvaluationCaseRunEntry.evaluation_run_id == run_pk)
                .order_by(EvaluationCaseRunEntry.id)
            ).all()
        )
    ]


def get_case_run(session: Session, run_pk: int, case_run_pk: int) -> CaseRunOut:
    """单条 CaseRun（归属校验，契约 §5 GET /runs/{id}/cases/{case_run_id}）。"""
    run = _get_run(session, run_pk)
    task = session.get(EvaluationTaskEntry, run.task_id)
    case_map = _snapshot_case_map(task) if task else {}
    entry = session.get(EvaluationCaseRunEntry, case_run_pk)
    if entry is None or entry.evaluation_run_id != run.id:
        raise EvaluationNotFoundError(f"用例运行 {case_run_pk} 不存在")
    return _to_case_run_out(
        entry,
        snapshot_case=case_map.get(entry.dataset_case_id),
        case_index=0,
    )


# ---- 聚合（FR-020，data-model.md §5；Invariant 8/9）----


def _effective_case_runs(
    session: Session, run_pk: int,
) -> list[EvaluationCaseRunEntry]:
    """每 dataset_case 取最新非取消 CaseRun（聚合统计集合）。"""
    entries = session.scalars(
        select(EvaluationCaseRunEntry)
        .where(EvaluationCaseRunEntry.evaluation_run_id == run_pk,
               EvaluationCaseRunEntry.status != "cancelled")
        .order_by(EvaluationCaseRunEntry.id)
    ).all()
    latest: dict[int, EvaluationCaseRunEntry] = {}
    for entry in entries:  # id 升序遍历：后写覆盖 = 每 Case 最新一条
        latest[entry.dataset_case_id] = entry
    return list(latest.values())


def aggregate_run(session: Session, run_pk: int) -> EvaluationRunOut:
    """按聚合口径重算并落库 Run 汇总（FR-020；失败不计 0 分）。

    计数（集合口径）：
    - passed/failed：有效评分（PASSED/FAILED）
    - execution_failed / judge_failed / cancelled：对应终态计数
    - completed_cases = passed + failed + execution_failed + judge_failed
    - average_score / pass_rate：分母 = 有效评分数；无有效评分 = NULL
    """
    run = _get_run(session, run_pk)
    latest = _effective_case_runs(session, run_pk)
    passed = sum(1 for c in latest if c.status == "passed")
    failed = sum(1 for c in latest if c.status == "failed")
    exec_failed = sum(1 for c in latest if c.status == "execution_failed")
    judge_failed = sum(1 for c in latest if c.status == "judge_failed")
    cancelled = session.scalar(
        select(func.count(EvaluationCaseRunEntry.id))
        .where(EvaluationCaseRunEntry.evaluation_run_id == run_pk,
               EvaluationCaseRunEntry.status == "cancelled")
    )
    scores = [
        c.score for c in latest
        if c.status in ("passed", "failed") and c.score is not None
    ]
    run.average_score = round(sum(scores) / len(scores)) if scores else None
    run.pass_rate = round(passed * 100 / len(scores)) if scores else None
    run.passed_cases = passed
    run.failed_cases = failed
    run.execution_failed_cases = exec_failed
    run.judge_failed_cases = judge_failed
    run.cancelled_cases = int(cancelled or 0)
    run.completed_cases = passed + failed + exec_failed + judge_failed
    tokens = [
        c.total_tokens for c in latest
        if c.total_tokens is not None
    ]
    run.total_tokens = sum(tokens) if tokens else None
    session.commit()
    return _to_run_out(run)


def finish_run(
    session: Session, run_pk: int,
    *,
    final_status: str,
    duration_ms: int | None = None,
) -> EvaluationRunOut:
    """运行收尾：状态机合法跳转 + 聚合重算 + 终态时间（FR-023）。"""
    run = _get_run(session, run_pk)
    if run.status == final_status:  # 幂等：重复收尾（如取消竞态）直接聚合返回
        return aggregate_run(session, run_pk)
    snapshot_mod.transition_run_status(run, final_status)
    finished = _utcnow()
    run.finished_at = finished
    if duration_ms is None and run.started_at is not None:
        duration_ms = int((finished - run.started_at).total_seconds() * 1000)
    run.total_duration_ms = duration_ms
    session.commit()
    return aggregate_run(session, run_pk)


# ---- 创建运行与重启恢复（FR-026，Invariant 13）----


def create_run_for_task(
    session: Session, task_pk: int,
) -> EvaluationRunOut:
    """为任务创建评测运行并按快照展开 PENDING CaseRun（FR-005/007）。

    幂等边界由调用方（runner.start_evaluation_run）负责；本函数只建行。
    """
    task = session.get(EvaluationTaskEntry, task_pk)
    if task is None:
        raise EvaluationNotFoundError(f"评测任务 {task_pk} 不存在")
    cases = (task.dataset_snapshot or {}).get("cases", [])
    if not cases:
        raise EvaluationValidationError("任务数据集快照为空，无法发起评测")
    run = EvaluationRunEntry(
        task_id=task.id,
        run_id=snapshot_mod.new_run_uuid(),
        status="pending",
        total_cases=len(cases),
    )
    session.add(run)
    session.flush()
    for case in cases:
        session.add(EvaluationCaseRunEntry(
            evaluation_run_id=run.id,
            dataset_case_id=int(case.get("case_id", 0)),
            status="pending",
        ))
    session.commit()
    return _to_run_out(run)


def mark_interrupted_runs(session: Session) -> int:
    """启动恢复（FR-026 / Invariant 13）：RUNNING/PAUSED → INTERRUPTED。

    对应 PENDING/RUNNING CaseRun → CANCELLED（error_type=interrupted）。
    PAUSED 为安全边界状态，重启后按中断处理，不自动恢复执行。
    """
    runs = session.scalars(
        select(EvaluationRunEntry)
        .where(EvaluationRunEntry.status.in_(("running", "paused")))
    ).all()
    now = _utcnow()
    for run in runs:
        run.status = "interrupted"
        run.interrupted_at = now
        run.interrupted_reason = RUN_INTERRUPTED_REASON
        unfinished = session.scalars(
            select(EvaluationCaseRunEntry)
            .where(EvaluationCaseRunEntry.evaluation_run_id == run.id,
                   EvaluationCaseRunEntry.status.in_(("pending", "running")))
        ).all()
        for entry in unfinished:
            entry.status = "cancelled"
            entry.error_type = "interrupted"
            entry.error_message = RUN_INTERRUPTED_REASON
            entry.finished_at = now
        if run.started_at is not None:
            run.total_duration_ms = int(
                (now - run.started_at).total_seconds() * 1000)
    if runs:
        session.commit()
    logger.info("[evaluation] 启动恢复：%s 个评测运行标记为已中断", len(runs))
    return len(runs)

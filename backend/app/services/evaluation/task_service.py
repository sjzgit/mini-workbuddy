"""评测任务服务：任务 CRUD 与三类快照固化（specs/012，US2，FR-004~008）。

契约主定义：specs/012-agent-evaluation/contracts/evaluation-api.md §4
快照创建时一次性固化，之后任何路径不更新（Invariant 5/6/7）。
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AgentEntry,
    EvaluationCaseEntry,
    EvaluationDatasetEntry,
    EvaluationRunEntry,
    EvaluationTaskEntry,
)
from app.schemas.evaluation import TaskOut, TaskSummary
from app.services.evaluation import snapshots as snapshot_builder

logger = logging.getLogger(__name__)


class TaskNotFoundError(LookupError):
    """评测任务不存在（路由层转 404）。"""


class TaskValidationError(ValueError):
    """任务业务校验失败（路由层转 422）。"""


def _get_task(session: Session, task_id: int) -> EvaluationTaskEntry:
    entry = session.get(EvaluationTaskEntry, task_id)
    if entry is None:
        raise TaskNotFoundError(f"评测任务 {task_id} 不存在")
    return entry


def _agent_name(session: Session, agent_id: int) -> str:
    agent = session.get(AgentEntry, agent_id)
    return agent.name if agent else ""


def _dataset_name(session: Session, dataset_id: int) -> str:
    dataset = session.get(EvaluationDatasetEntry, dataset_id)
    return dataset.name if dataset else ""


def _to_summary(
    session: Session, entry: EvaluationTaskEntry,
) -> TaskSummary:
    last_run = session.scalar(
        select(EvaluationRunEntry)
        .where(EvaluationRunEntry.task_id == entry.id)
        .order_by(EvaluationRunEntry.id.desc())
        .limit(1)
    )
    # case_count 从快照取（数据集后续变化不影响任务呈现）
    case_count = len((entry.dataset_snapshot or {}).get("cases", []))
    return TaskSummary(
        id=entry.id,
        name=entry.name,
        agent_id=entry.agent_id,
        agent_name=_agent_name(session, entry.agent_id),
        dataset_id=entry.dataset_id,
        dataset_name=_dataset_name(session, entry.dataset_id) or
        str((entry.dataset_snapshot or {}).get("name", "")),
        evaluator_type=entry.evaluator_type,
        evaluator_config=entry.evaluator_config or {},
        pass_threshold=entry.pass_threshold,
        status=entry.status,
        case_count=case_count,
        last_run_id=last_run.id if last_run else None,
        last_run_status=last_run.status if last_run else None,
        created_at=entry.created_at.isoformat(),
        updated_at=entry.updated_at.isoformat(),
    )


def _to_out(session: Session, entry: EvaluationTaskEntry) -> TaskOut:
    return TaskOut(
        **_to_summary(session, entry).model_dump(),
        agent_snapshot=entry.agent_snapshot or {},
        dataset_snapshot=entry.dataset_snapshot or {},
        evaluator_snapshot=entry.evaluator_snapshot or {},
    )


def create_task(
    session: Session,
    name: str,
    agent_id: int,
    dataset_id: int,
    evaluator_type: str,
    evaluator_config: dict,
    pass_threshold: int,
) -> TaskOut:
    """创建任务并固化三快照（FR-004~008）。

    校验：agent/dataset 存在、dataset 非空、evaluator_config 按 type 校验。
    """
    if session.get(AgentEntry, agent_id) is None:
        raise TaskValidationError(f"Agent {agent_id} 不存在")
    dataset = session.get(EvaluationDatasetEntry, dataset_id)
    if dataset is None:
        raise TaskValidationError(f"数据集 {dataset_id} 不存在")
    case_count = session.scalar(
        select(func.count(EvaluationCaseEntry.id))
        .where(EvaluationCaseEntry.dataset_id == dataset_id)
    )
    if not case_count:
        raise TaskValidationError("数据集没有任何评测用例，无法创建评测任务")

    agent_snapshot = snapshot_builder.build_agent_snapshot(session, agent_id)
    dataset_snapshot = snapshot_builder.build_dataset_snapshot(session, dataset_id)
    try:
        evaluator_snapshot = snapshot_builder.build_evaluator_snapshot(
            session, evaluator_type, evaluator_config, pass_threshold,
        )
    except snapshot_builder.SnapshotBuildError as exc:
        raise TaskValidationError(str(exc)) from exc

    entry = EvaluationTaskEntry(
        name=name.strip(),
        agent_id=agent_id,
        dataset_id=dataset_id,
        evaluator_type=evaluator_type,
        evaluator_config=dict(evaluator_config),
        pass_threshold=pass_threshold,
        agent_snapshot=agent_snapshot,
        dataset_snapshot=dataset_snapshot,
        evaluator_snapshot=evaluator_snapshot,
        status="pending",
    )
    session.add(entry)
    session.commit()
    logger.info("[evaluation] 任务创建 id=%s name=%s agent=%s dataset=%s cases=%s",
                entry.id, entry.name, agent_id, dataset_id, case_count)
    return _to_out(session, entry)


def list_tasks(session: Session) -> list[TaskSummary]:
    entries = session.scalars(
        select(EvaluationTaskEntry)
        .order_by(EvaluationTaskEntry.updated_at.desc(),
                  EvaluationTaskEntry.id.desc())
    ).all()
    return [_to_summary(session, entry) for entry in entries]


def get_task(session: Session, task_id: int) -> TaskOut:
    return _to_out(session, _get_task(session, task_id))


def delete_task(session: Session, task_id: int) -> None:
    """删除任务并显式清理 Runs/CaseRuns（契约 §4；SQLite 级联需 PRAGMA，
    项目先例为 service 层显式清理）。快照随任务删除。"""
    entry = _get_task(session, task_id)
    run_rows = session.scalars(
        select(EvaluationRunEntry).where(EvaluationRunEntry.task_id == entry.id),
    ).all()
    from app.models import EvaluationCaseRunEntry

    for run in run_rows:
        session.query(EvaluationCaseRunEntry).filter_by(
            evaluation_run_id=run.id,
        ).delete(synchronize_session=False)
    for run in run_rows:
        session.delete(run)
    session.delete(entry)
    session.commit()

"""评测执行引擎（specs/012，US3/US5，FR-009~013、FR-024~027）。

架构红线（Invariants 1/2）：Agent 执行只经 execute_run——
本模块仅做编排（Case 顺序、状态推进、评分调度、聚合），
不实现任何 Agent Loop / Tool Calling / Context 构建逻辑。
"""

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.core.db import SessionLocal
from sqlalchemy import select
from app.services.agent_runtime import RunRequest, execute_run
from app.services.agent_runtime import events as rt_events

from app.services.evaluation import evaluators as evaluator_mod

logger = logging.getLogger(__name__)

# AgentRun 终态 → CaseRun 执行失败错误类型（contract CaseErrorType）
_RUNTIME_ERROR_CATEGORY = {
    "unreachable": "model_error",
    "timeout": "timeout",
    "auth_error": "model_error",
    "model_not_found": "model_error",
    "bad_response": "model_error",
    "empty_response": "model_error",
    "context_overflow": "model_error",
    "unknown": "model_error",
}


@dataclass
class EvaluationRunControl:
    """一次评测运行的后台控制柄（进程内注册表，D8）。"""

    run_pk: int
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    pause_event: asyncio.Event = field(default_factory=asyncio.Event)
    asyncio_task: asyncio.Task | None = None
    # 当前正在执行的 CaseRun 主键与 Runtime 取消事件（取消时联动置位）
    current_case_run_pk: int | None = None
    current_runtime_cancel: asyncio.Event | None = None

    @property
    def active(self) -> bool:
        return self.asyncio_task is not None and not self.asyncio_task.done()


# 进程内注册表：run_pk → 控制柄（先例：services/generation_registry.py）
RUN_CONTROLS: dict[int, EvaluationRunControl] = {}


class EvaluationRunActiveError(RuntimeError):
    """评测运行已在执行（路由层转 409）。"""


class ExecutionStrategy(ABC):
    """执行策略抽象（FR-013，需求 §15/§40）。"""

    @abstractmethod
    async def execute(self, case_items: list, worker) -> None:
        """调度全部 CaseItem 交给 worker 执行；策略只决定调度顺序。"""


class SequentialExecutionStrategy(ExecutionStrategy):
    """顺序执行策略：逐 Case await；单 Case 异常不外抛（FR-012 失败隔离）。"""

    async def execute(self, case_items: list, worker) -> None:
        for item in case_items:
            await worker(item)


# ---- 单 Case 执行（worker）----


@dataclass
class CaseItem:
    """worker 的单个 Case 输入（来自任务 dataset_snapshot）。"""

    case_run_pk: int
    dataset_case_id: int
    user_question: str
    expected_answer: str | None
    scoring_criteria: str | None
    case_index: int


@dataclass
class _CaseRunOutcome:
    """worker 内部对一次 Case 执行的终态汇总。"""

    status: str
    score: int | None = None
    reason: str | None = None
    evaluator_type: str | None = None
    evaluator_metadata: dict | None = None
    duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    tool_call_count: int | None = None
    model_call_count: int | None = None
    iteration_count: int | None = None
    error_type: str | None = None
    error_message: str | None = None


def _map_runtime_error(category: str) -> str:
    return _RUNTIME_ERROR_CATEGORY.get(category, "model_error")


async def _consume_agent_run(
    request: RunRequest,
) -> tuple[str, str, str, _CaseRunOutcome]:
    """消费 execute_run 事件流 → (终态 status, content, reason, 指标)。

    指标来源均为真实事件（FR-021）：
    model_call_count=model_request_started 计数；
    tool_call_count=tool_call_completed(success/error/cancelled) 计数；
    tool_error_count 口径并入 tool_call_count（计数仍保留工具侧数据于 AgentRun）；
    iteration_count=最后一个 model_request 的 round；
    tokens=run_completed.usage_total（未知保持 None，不填零）。
    """
    model_call_count = 0
    tool_call_count = 0
    last_round = 0
    usage_total = None
    content_text = ""
    final_status = "error"
    final_reason = ""
    async for event in execute_run(request):
        name = event.event
        data = event.data
        if name == rt_events.EVENT_MODEL_REQUEST_STARTED:
            model_call_count += 1
            last_round = max(last_round, int(data.get("round", 0)))
        elif name == rt_events.EVENT_TOOL_CALL_COMPLETED:
            if str(data.get("status", "")) in ("success", "error", "cancelled"):
                tool_call_count += 1
        elif name == rt_events.EVENT_CONTENT_DELTA:
            text = str(data.get("text", ""))
            if text:
                content_text += text
        elif name == rt_events.EVENT_RUN_COMPLETED:
            final_status = str(data.get("status", "error"))
            final_reason = str(data.get("reason", ""))
            # 终态 content_text 为权威全文（增量缺失时兜底，如收尾轮）
            completed_text = str(data.get("content_text", ""))
            if completed_text:
                content_text = completed_text
            usage = data.get("usage_total")
            if isinstance(usage, dict):
                usage_total = usage
    outcome = _CaseRunOutcome(status="pending")
    outcome.model_call_count = model_call_count
    outcome.tool_call_count = tool_call_count
    outcome.iteration_count = last_round or None
    if usage_total is not None:
        outcome.input_tokens = usage_total.get("prompt_tokens")
        outcome.output_tokens = usage_total.get("completion_tokens")
        outcome.total_tokens = usage_total.get("total_tokens")
    return final_status, content_text, final_reason, outcome


async def execute_case_run(
    control: EvaluationRunControl,
    item: CaseItem,
    *,
    evaluator_type: str,
    pass_threshold: int,
    evaluator_snapshot: dict,
    evaluation_run_id: str,
) -> _CaseRunOutcome:
    """执行单个 CaseRun：Runtime 执行 → 评分 → 终态（FR-009~018）。

    失败隔离：本函数不向策略外抛业务异常；任何失败都转为对应终态
    （EXECUTION_FAILED / JUDGE_FAILED / CANCELLED），不判 0 分（FR-019）。
    """
    started = time.monotonic()
    agent_run_id = uuid.uuid4().hex
    from app.core.db import SessionLocal as _SL
    from app.models import EvaluationCaseRunEntry

    control.current_case_run_pk = item.case_run_pk
    runtime_cancel = control.current_runtime_cancel
    cancel = runtime_cancel if runtime_cancel is not None else control.cancel_event

    def _duration() -> int:
        return int((time.monotonic() - started) * 1000)

    logger.info(
        "[evaluation] case_run=%s 开始执行 run=%s agent_run=%s",
        item.case_run_pk, evaluation_run_id, agent_run_id,
    )
    # ① 标记 RUNNING（独立短会话，状态即时可见）
    with SessionLocal() as session:
        entry = session.get(EvaluationCaseRunEntry, item.case_run_pk)
        if entry is None:
            control.current_case_run_pk = None
            return _CaseRunOutcome(status="execution_failed",
                                   error_type="internal",
                                   error_message="CaseRun 行不存在")
        entry.status = "running"
        entry.agent_run_id = agent_run_id
        entry.started_at = _now()
        session.commit()

    # ② Agent 执行（唯一入口：execute_run；独立上下文 = history 空 + 无 conversation）
    request = RunRequest(
        agent_id=_resolve_agent_id(item),
        user_message=item.user_question,
        history=[],
        conversation_id=None,
        reply_message_id=None,
        run_id=agent_run_id,
        cancel=runtime_cancel if runtime_cancel is not None else control.cancel_event,
    )
    try:
        runtime_status, content_text, runtime_reason, metrics = await _consume_agent_run(request)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — 失败隔离：异常转执行失败（FR-012）
        logger.exception("[evaluation] case_run=%s 执行异常", item.case_run_pk)
        outcome = _CaseRunOutcome(
            status="execution_failed", error_type="internal",
            error_message=str(exc)[:2000], duration_ms=_duration(),
        )
        return _persist_case_run_terminal(
            item.case_run_pk, outcome,
            evaluation_run_id=evaluation_run_id,
        )

    if control.cancel_event.is_set() or runtime_status == "cancelled":
        outcome = _CaseRunOutcome(
            status="cancelled", error_type="cancelled",
            error_message="评测被取消",
            model_call_count=metrics.model_call_count,
            tool_call_count=metrics.tool_call_count,
        )
        return _persist_case_run_terminal(
            item.case_run_pk, outcome,
            evaluation_run_id=evaluation_run_id,
        )

    if runtime_status not in ("completed", "max_rounds") or not content_text.strip():
        category = _map_runtime_error(runtime_reason or runtime_status)
        outcome = _CaseRunOutcome(
            status="execution_failed", error_type=category,
            error_message=runtime_reason or f"Agent 运行终态异常：{runtime_status}",
            model_call_count=metrics.model_call_count,
            tool_call_count=metrics.tool_call_count,
            iteration_count=metrics.iteration_count,
            input_tokens=metrics.input_tokens,
            output_tokens=metrics.output_tokens,
            total_tokens=metrics.total_tokens,
            duration_ms=_duration(),
        )
        return _persist_case_run_terminal(
            item.case_run_pk, outcome,
            evaluation_run_id=evaluation_run_id,
        )

    # ③ 评分（Evaluator；评分失败不判 0 分，FR-017/019）
    evaluator = evaluator_mod.get_evaluator(evaluator_type)
    try:
        result = await evaluator.evaluate(
            question=item.user_question,
            expected_answer=item.expected_answer,
            scoring_criteria=item.scoring_criteria,
            actual_answer=content_text,
            evaluator_snapshot=evaluator_snapshot,
        )
    except evaluator_mod.JudgeModelUnavailableError as exc:
        outcome = _CaseRunOutcome(
            status="judge_failed", error_type="judge_model_error",
            error_message=str(exc)[:2000],
            model_call_count=metrics.model_call_count,
            tool_call_count=metrics.tool_call_count,
            duration_ms=_duration(),
        )
        return _persist_case_run_terminal(
            item.case_run_pk, outcome,
            evaluation_run_id=evaluation_run_id,
        )
    except evaluator_mod.JudgeInvalidOutput as exc:
        outcome = _CaseRunOutcome(
            status="judge_failed", error_type="judge_invalid_output",
            error_message=str(exc)[:2000],
            model_call_count=metrics.model_call_count,
            tool_call_count=metrics.tool_call_count,
            duration_ms=_duration(),
        )
        return _persist_case_run_terminal(
            item.case_run_pk, outcome,
            evaluation_run_id=evaluation_run_id,
        )

    # ④ 有效评分终态（score < threshold → FAILED；Invariant 8/9 已保证失败不判 0）
    outcome = _CaseRunOutcome(
        status=result.status,
        score=result.score,
        reason=result.reason,
        evaluator_type=result.evaluator_type,
        evaluator_metadata=result.metadata,
        model_call_count=metrics.model_call_count,
        tool_call_count=metrics.tool_call_count,
        iteration_count=metrics.iteration_count,
        input_tokens=metrics.input_tokens,
        output_tokens=metrics.output_tokens,
        total_tokens=metrics.total_tokens,
        duration_ms=_duration(),
    )
    return _persist_case_run_terminal(
        item.case_run_pk, outcome,
        evaluation_run_id=evaluation_run_id,
    )


# ---- 辅助：agent 解析与终态落库 ----


def _resolve_agent_id(item: CaseItem) -> int:
    """按快照 case_id 反查所属任务的 agent_id（执行时当前库配置，research D3）。

    CaseRun → EvaluationRun → EvaluationTask.agent_id。
    """
    from app.models import EvaluationCaseRunEntry, EvaluationRunEntry, EvaluationTaskEntry

    with SessionLocal() as session:
        case_run = session.get(EvaluationCaseRunEntry, item.case_run_pk)
        run = session.get(EvaluationRunEntry, case_run.evaluation_run_id)
        task = session.get(EvaluationTaskEntry, run.task_id)
        return task.agent_id


def _persist_case_run_terminal(
    case_run_pk: int,
    outcome: _CaseRunOutcome,
    *,
    evaluation_run_id: str,
) -> _CaseRunOutcome:
    """CaseRun 终态一次性落库（幂等：终态行仅写一次）。"""
    from app.models import EvaluationCaseRunEntry

    with SessionLocal() as session:
        entry = session.get(EvaluationCaseRunEntry, case_run_pk)
        if entry is None:
            return outcome
        entry.status = outcome.status
        entry.score = outcome.score
        entry.reason = outcome.reason
        entry.evaluator_type = outcome.evaluator_type
        entry.evaluator_metadata = outcome.evaluator_metadata
        entry.duration_ms = outcome.duration_ms
        entry.input_tokens = outcome.input_tokens
        entry.output_tokens = outcome.output_tokens
        entry.total_tokens = outcome.total_tokens
        entry.tool_call_count = outcome.tool_call_count
        entry.model_call_count = outcome.model_call_count
        entry.iteration_count = outcome.iteration_count
        entry.error_type = outcome.error_type
        entry.error_message = outcome.error_message
        entry.finished_at = _now()
        session.commit()
    logger.info(
        "[evaluation] case_run=%s 终态=%s score=%s run=%s",
        case_run_pk, outcome.status, outcome.score, evaluation_run_id,
    )
    return outcome


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


# ---- 运行启动与后台主循环（FR-012/013/024/027）----


def start_evaluation_run(run_pk: int) -> None:
    """启动（或续跑）一个评测运行的后台任务。

    幂等边界（FR-027）：注册表已有活跃控制 → 拒绝（409 语义）；
    数据库状态必须可启动（pending/interrupted）。由 API 层先建行后调用。
    """
    existing = RUN_CONTROLS.get(run_pk)
    if existing is not None and existing.active:
        raise EvaluationRunActiveError(f"评测运行 {run_pk} 正在执行中")
    control = EvaluationRunControl(run_pk=run_pk)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as exc:
        # 必须在事件循环线程调用（async 路由）；同步线程 = 后台任务无法调度（bug 防线）
        raise RuntimeError(
            "start_evaluation_run 必须在事件循环内调用（路由需为 async def）",
        ) from exc
    control.asyncio_task = loop.create_task(_run_evaluation_loop(control))
    RUN_CONTROLS[run_pk] = control


async def _run_evaluation_loop(control: EvaluationRunControl) -> None:
    """后台主循环：读快照 → ExecutionStrategy 调度 worker → 聚合收尾。"""
    from app.models import EvaluationCaseRunEntry, EvaluationRunEntry, EvaluationTaskEntry
    from app.services.evaluation import run_service

    run_pk = control.run_pk
    try:
        with SessionLocal() as session:
            run = session.get(EvaluationRunEntry, run_pk)
            if run is None:
                return
            if run.status in ("pending", "paused"):
                # pending = 首次启动；paused = 恢复（resume，FR-024）
                run.status = "running"
            elif run.status == "interrupted":
                # 中断后续跑：状态机允许 interrupted → running
                run.status = "running"
                run.interrupted_at = None
                run.interrupted_reason = None
            else:
                return
            if run.started_at is None:
                run.started_at = _now()
            task = session.get(EvaluationTaskEntry, run.task_id)
            run_uuid = run.run_id
            evaluator_type = task.evaluator_type
            evaluator_snapshot = task.evaluator_snapshot or {}
            evaluator_snapshot["agent_id"] = task.agent_id
            session.commit()

            # 待执行 CaseRun → CaseItem（每 Case 最新一条 PENDING；历史终态行不动）
            pending_rows = session.scalars(
                select(EvaluationCaseRunEntry)
                .where(EvaluationCaseRunEntry.evaluation_run_id == run_pk,
                       EvaluationCaseRunEntry.status == "pending")
                .order_by(EvaluationCaseRunEntry.id)
            ).all()
            case_map = {
                int(c.get("case_id", 0)): c
                for c in (task.dataset_snapshot or {}).get("cases", [])
                if isinstance(c, dict)
            }
            items = [
                CaseItem(
                    case_run_pk=row.id,
                    dataset_case_id=row.dataset_case_id,
                    user_question=str((case_map.get(row.dataset_case_id) or {}).get("user_question", "")),
                    expected_answer=(case_map.get(row.dataset_case_id) or {}).get("expected_answer"),
                    scoring_criteria=(case_map.get(row.dataset_case_id) or {}).get("scoring_criteria"),
                    case_index=index,
                )
                for index, row in enumerate(pending_rows)
            ]
            strategy = SequentialExecutionStrategy()
    except Exception:  # noqa: BLE001
        logger.exception("[evaluation] run=%s 启动失败", run_pk)
        with SessionLocal() as session:
            run_service.finish_run(session, run_pk, final_status="failed")
        RUN_CONTROLS.pop(run_pk, None)
        return

    # worker：单 Case 执行 + 暂停/取消边界检查
    async def worker(item: CaseItem) -> None:
        if control.cancel_event.is_set():
            return
        if control.pause_event.is_set():
            return
        runtime_cancel = asyncio.Event()
        control.current_runtime_cancel = runtime_cancel
        control.current_case_run_pk = item.case_run_pk
        try:
            await execute_case_run(
                control, item,
                evaluator_type=evaluator_type,
                pass_threshold=int((evaluator_snapshot or {}).get("pass_threshold", 80)),
                evaluator_snapshot=evaluator_snapshot,
                evaluation_run_id=run_uuid,
            )
        except asyncio.CancelledError:
            raise
        finally:
            control.current_case_run_pk = None
            control.current_runtime_cancel = None

    try:
        await strategy.execute(items, worker)

        # 取消：未启动 CaseRun 批量 CANCELLED
        if control.cancel_event.is_set():
            with SessionLocal() as session:
                pending_rows = session.scalars(
                    select(EvaluationCaseRunEntry)
                    .where(EvaluationCaseRunEntry.evaluation_run_id == run_pk,
                           EvaluationCaseRunEntry.status.in_(("pending", "running")))
                ).all()
                for row in pending_rows:
                    row.status = "cancelled"
                    row.error_type = "cancelled"
                    row.error_message = "评测被取消"
                    row.finished_at = _now()
                session.commit()
                await _finalize(control, run_pk, "cancelled")
                return

        # 暂停：Case 边界软停（FR-024 暂停语义）
        if control.pause_event.is_set():
            with SessionLocal() as session:
                run = session.get(EvaluationRunEntry, run_pk)
                if run is not None and run.status == "running":
                    run.status = "paused"
                    session.commit()
            return

        await _finalize(control, run_pk, "completed")
    except asyncio.CancelledError:
        # 协作取消收尾（Case 级已在 worker 内落 CANCELLED）；这里只兜运行终态。
        # 不再 re-raise：评测后台任务被取消属正常路径，避免测试事件循环报未捕获取消。
        with SessionLocal() as session:
            run_service.finish_run(session, run_pk, final_status="cancelled")
    except Exception:  # noqa: BLE001 — 框架级异常 → FAILED（Case 级已在 worker 内隔离）
        logger.exception("[evaluation] run=%s 执行框架异常", run_pk)
        with SessionLocal() as session:
            run_service.finish_run(session, run_pk, final_status="failed")
    finally:
        RUN_CONTROLS.pop(run_pk, None)


async def _finalize(control: EvaluationRunControl, run_pk: int, status: str) -> None:
    from app.services.evaluation import run_service

    with SessionLocal() as session:
        run_service.finish_run(session, run_pk, final_status=status)


# ---- 运行控制（FR-024/025/027，US5）----


def pause_evaluation_run(run_pk: int) -> None:
    """暂停：置暂停标志，当前 Case 完成后不再启动下一个（软停，FR-024）。"""
    control = RUN_CONTROLS.get(run_pk)
    if control is None or not control.active:
        raise EvaluationRunActiveError(f"评测运行 {run_pk} 不在执行中")
    control.pause_event.set()


def resume_evaluation_run(run_pk: int) -> None:
    """恢复：清除暂停标志并续跑（若后台任务已结束则重新启动）。"""
    from app.models import EvaluationRunEntry

    control = RUN_CONTROLS.get(run_pk)
    if control is not None and control.active:
        control.pause_event.clear()
        return
    from app.services.evaluation.run_service import EvaluationNotFoundError

    with SessionLocal() as session:
        run = session.get(EvaluationRunEntry, run_pk)
        if run is None:
            raise EvaluationNotFoundError(f"评测运行 {run_pk} 不存在")
        if run.status != "paused":
            raise EvaluationRunActiveError(f"评测运行 {run_pk} 不处于暂停状态")
    control = EvaluationRunControl(run_pk=run_pk)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as exc:
        raise RuntimeError(
            "resume_evaluation_run 必须在事件循环内调用（路由需为 async def）",
        ) from exc
    control.asyncio_task = loop.create_task(_run_evaluation_loop(control))
    RUN_CONTROLS[run_pk] = control


def cancel_evaluation_run(run_pk: int) -> None:
    """取消：置取消标志并联动当前 Case 的 Runtime 协作取消（FR-024）。

    幂等：控制柄不存在或任务已结束也照常置数据库终态（由调用方兜底）。
    """
    control = RUN_CONTROLS.get(run_pk)
    if control is not None:
        control.cancel_event.set()
        runtime_cancel = control.current_runtime_cancel
        if runtime_cancel is not None:
            runtime_cancel.set()


def retry_case_run(
    run_pk: int, case_run_pk: int,
) -> tuple[int, int]:
    """失败 Case 重试：新建 attempt+1 CaseRun（原行不动，Invariant 12）。

    返回 (run_pk, 新 case_run_pk)；运行非 RUNNING 时由调用方置回 RUNNING
    并 start_evaluation_run 续跑（仅消费 PENDING CaseRun）。
    """
    from app.models import EvaluationCaseRunEntry, EvaluationRunEntry
    from app.schemas.evaluation import RETRYABLE_CASE_RUN_STATUSES

    from app.services.evaluation.run_service import EvaluationNotFoundError

    with SessionLocal() as session:
        run = session.get(EvaluationRunEntry, run_pk)
        if run is None:
            raise EvaluationNotFoundError(f"评测运行 {run_pk} 不存在")
        target = session.get(EvaluationCaseRunEntry, case_run_pk)
        if target is None or target.evaluation_run_id != run_pk:
            raise EvaluationNotFoundError(f"用例运行 {case_run_pk} 不存在")
        if target.status not in RETRYABLE_CASE_RUN_STATUSES:
            raise EvaluationRunActiveError(
                f"用例运行状态 {target.status} 不允许重试",
            )
        retry_row = EvaluationCaseRunEntry(
            evaluation_run_id=run_pk,
            dataset_case_id=target.dataset_case_id,
            status="pending",
            attempt=target.attempt + 1,
        )
        session.add(retry_row)
        should_restart = run.status != "running"  # pending/终态：重试即发起续跑
        if should_restart:
            run.status = "running"
        session.commit()
        new_pk = retry_row.id
    return run_pk, new_pk

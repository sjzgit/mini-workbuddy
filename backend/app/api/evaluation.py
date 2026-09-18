"""评测 API 路由（specs/012，契约主定义 contracts/evaluation-api.md）。

路由层薄：异常 → HTTP 状态映射 + 调 service/runner。
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.schemas.evaluation import (
    RUN_PAGE_DEFAULT,
    RUN_PAGE_SIZE_DEFAULT,
    RUN_PAGE_SIZE_MAX,
    RUN_STATUSES,
    CaseOut,
    CaseRunOut,
    CaseSaveRequest,
    DatasetOut,
    DatasetSaveRequest,
    EvaluationRunOut,
    ImportResult,
    OkResponse,
    RetryRequest,
    RetryResponse,
    RunListResponse,
    TaskOut,
    TaskSaveRequest,
    TaskSummary,
)
from app.services.evaluation import dataset_service, task_service
from app.services.evaluation import run_service as eval_run_service
from app.services.evaluation import runner as eval_runner

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


# ---- 数据集（契约 §1）----


@router.post("/datasets", response_model=DatasetOut, status_code=201)
def create_dataset(
    payload: DatasetSaveRequest, session: Session = Depends(get_session),
) -> object:
    return dataset_service.create_dataset(session, payload.name, payload.description)


@router.get("/datasets", response_model=list[DatasetOut])
def list_datasets(session: Session = Depends(get_session)) -> object:
    return dataset_service.list_datasets(session)


@router.get("/datasets/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: int, session: Session = Depends(get_session)) -> object:
    try:
        return dataset_service.get_dataset(session, dataset_id)
    except dataset_service.DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/datasets/{dataset_id}", response_model=DatasetOut)
def update_dataset(
    dataset_id: int, payload: DatasetSaveRequest,
    session: Session = Depends(get_session),
) -> object:
    try:
        return dataset_service.update_dataset(
            session, dataset_id, payload.name, payload.description,
        )
    except dataset_service.DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/datasets/{dataset_id}", response_model=OkResponse)
def delete_dataset(dataset_id: int, session: Session = Depends(get_session)) -> object:
    try:
        dataset_service.delete_dataset(session, dataset_id)
    except dataset_service.DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return OkResponse()


# ---- 数据集用例（契约 §2）----


@router.get("/datasets/{dataset_id}/cases", response_model=list[CaseOut])
def list_cases(dataset_id: int, session: Session = Depends(get_session)) -> object:
    try:
        return dataset_service.list_cases(session, dataset_id)
    except dataset_service.DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/datasets/{dataset_id}/cases", response_model=CaseOut, status_code=201)
def create_case(
    dataset_id: int, payload: CaseSaveRequest,
    session: Session = Depends(get_session),
) -> object:
    try:
        return dataset_service.create_case(
            session, dataset_id,
            payload.user_question, payload.expected_answer,
            payload.scoring_criteria,
        )
    except dataset_service.DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/datasets/{dataset_id}/cases/{case_id}", response_model=CaseOut)
def update_case(
    dataset_id: int, case_id: int, payload: CaseSaveRequest,
    session: Session = Depends(get_session),
) -> object:
    try:
        return dataset_service.update_case(
            session, dataset_id, case_id,
            payload.user_question, payload.expected_answer,
            payload.scoring_criteria,
        )
    except dataset_service.DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except dataset_service.DatasetCaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/datasets/{dataset_id}/cases/{case_id}", response_model=OkResponse)
def delete_case(
    dataset_id: int, case_id: int, session: Session = Depends(get_session),
) -> object:
    try:
        dataset_service.delete_case(session, dataset_id, case_id)
    except dataset_service.DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except dataset_service.DatasetCaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return OkResponse()


# ---- JSON 导入导出（契约 §3）----


@router.post("/datasets/{dataset_id}/import", response_model=ImportResult)
def import_dataset(
    dataset_id: int, payload: dict,
    session: Session = Depends(get_session),
) -> object:
    try:
        return dataset_service.import_cases(session, dataset_id, payload)
    except dataset_service.DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except dataset_service.ImportValidationError as exc:
        raise HTTPException(status_code=422, detail="；".join(exc.errors[:5])) from exc


@router.get("/datasets/{dataset_id}/export")
def export_dataset(dataset_id: int, session: Session = Depends(get_session)):
    try:
        data = dataset_service.export_dataset(session, dataset_id)
    except dataset_service.DatasetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    content = json.dumps(data, ensure_ascii=False, indent=2)
    filename = f"dataset-{dataset_id}.json"
    return Response(
        content=content, media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---- 评测任务（契约 §4）----


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskSaveRequest, session: Session = Depends(get_session),
) -> object:
    try:
        return task_service.create_task(
            session, payload.name, payload.agent_id, payload.dataset_id,
            payload.evaluator_type, payload.evaluator_config,
            payload.pass_threshold,
        )
    except task_service.TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except task_service.TaskValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tasks", response_model=list[TaskSummary])
def list_tasks(session: Session = Depends(get_session)) -> object:
    return task_service.list_tasks(session)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, session: Session = Depends(get_session)) -> object:
    try:
        return task_service.get_task(session, task_id)
    except task_service.TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/tasks/{task_id}", response_model=OkResponse)
def delete_task(task_id: int, session: Session = Depends(get_session)) -> object:
    try:
        task_service.delete_task(session, task_id)
    except task_service.TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return OkResponse()


# ---- 评测运行（契约 §5）----


@router.post("/tasks/{task_id}/runs", response_model=EvaluationRunOut, status_code=202)
async def start_run(task_id: int, session: Session = Depends(get_session)) -> object:
    """发起评测：创建 Run 与 PENDING CaseRun 后后台启动（幂等边界在 runner）。"""
    try:
        run_out = eval_run_service.create_run_for_task(session, task_id)
    except eval_run_service.EvaluationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except eval_run_service.EvaluationValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        eval_runner.start_evaluation_run(run_out.id)
    except eval_runner.EvaluationRunActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return run_out


@router.get("/runs", response_model=RunListResponse)
def list_runs(
    task_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=RUN_PAGE_DEFAULT, ge=1),
    page_size: int = Query(default=RUN_PAGE_SIZE_DEFAULT, ge=1),
    session: Session = Depends(get_session),
) -> object:
    if status is not None and status not in RUN_STATUSES:
        raise HTTPException(status_code=422, detail=f"status 需为 {RUN_STATUSES} 之一")
    return eval_run_service.list_runs(
        session, task_id=task_id, status=status,
        page=page, page_size=min(page_size, RUN_PAGE_SIZE_MAX),
    )


@router.get("/runs/{run_id}", response_model=EvaluationRunOut)
def get_run(run_id: int, session: Session = Depends(get_session)) -> object:
    try:
        return eval_run_service.get_run(session, run_id)
    except eval_run_service.EvaluationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/cases", response_model=list[CaseRunOut])
def list_run_cases(run_id: int, session: Session = Depends(get_session)) -> object:
    try:
        return eval_run_service.get_case_runs(session, run_id)
    except eval_run_service.EvaluationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/cases/{case_run_id}", response_model=CaseRunOut)
def get_run_case(
    run_id: int, case_run_id: int, session: Session = Depends(get_session),
) -> object:
    try:
        return eval_run_service.get_case_run(session, run_id, case_run_id)
    except eval_run_service.EvaluationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---- 运行控制（契约 §5；US5）----


@router.post("/runs/{run_id}/pause", response_model=EvaluationRunOut)
async def pause_run(run_id: int, session: Session = Depends(get_session)) -> object:
    try:
        eval_runner.pause_evaluation_run(run_id)
    except eval_runner.EvaluationRunActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    from app.services.evaluation.snapshots import transition_run_status

    run = eval_run_service._get_run(session, run_id)
    if run.status == "running":
        transition_run_status(run, "paused")
        session.commit()
    return eval_run_service.get_run(session, run_id)


@router.post("/runs/{run_id}/resume", response_model=EvaluationRunOut)
async def resume_run(run_id: int, session: Session = Depends(get_session)) -> object:
    try:
        eval_runner.resume_evaluation_run(run_id)
    except eval_run_service.EvaluationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except eval_runner.EvaluationRunActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return eval_run_service.get_run(session, run_id)


@router.post("/runs/{run_id}/cancel", response_model=EvaluationRunOut)
async def cancel_run(run_id: int, session: Session = Depends(get_session)) -> object:
    try:
        run = eval_run_service._get_run(session, run_id)
    except eval_run_service.EvaluationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if run.status == "cancelled":  # 幂等：已取消直接返回
        return eval_run_service.get_run(session, run_id)
    if run.status not in ("pending", "running", "paused"):
        raise HTTPException(status_code=409, detail=f"运行状态 {run.status} 不允许取消")
    eval_runner.cancel_evaluation_run(run_id)
    # 等待后台任务在安全边界收尾（异步任务自行置终态）；此处先持久化请求语义
    from app.services.evaluation.snapshots import transition_run_status

    try:
        transition_run_status(run, "cancelled")
        run.finished_at = run.finished_at or eval_run_service._utcnow()
        session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return eval_run_service.get_run(session, run_id)


@router.post("/runs/{run_id}/retry", response_model=RetryResponse)
async def retry_run(
    run_id: int, payload: RetryRequest, session: Session = Depends(get_session),
) -> object:
    try:
        _run_pk, new_case_run_pk = eval_runner.retry_case_run(run_id, payload.case_run_id)
    except eval_run_service.EvaluationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except eval_runner.EvaluationRunActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # 重试行创建后：重启后台消费（仅 PENDING CaseRun）
    try:
        eval_runner.start_evaluation_run(run_id)
    except eval_runner.EvaluationRunActiveError:
        pass  # 已在执行中：后台循环会自然消费新 PENDING 行
    run_out = eval_run_service.get_run(session, run_id)
    case_run_out = eval_run_service.get_case_run(session, run_id, new_case_run_pk)
    return RetryResponse(run=run_out, case_run=case_run_out)

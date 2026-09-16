"""运行记录路由（specs/011，契约 runs-api.md）。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.schemas.runs import PAGE_DEFAULT, PAGE_SIZE_DEFAULT, RunListResponse, RunStatusLiteral
from app.services import run_service

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("", response_model=RunListResponse)
def list_runs(
    status: str | None = Query(default=None),
    agent_id: int | None = Query(default=None),
    conversation_id: int | None = Query(default=None),
    page: int = Query(default=PAGE_DEFAULT, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1),
    session: Session = Depends(get_session),
) -> RunListResponse:
    """运行列表：started_at 倒序、分页、按状态/Agent/会话筛选（恒定 2 条 SQL）。"""
    if status is not None and status not in run_service.RUN_STATUSES:
        raise HTTPException(status_code=422, detail=f"status 需为 {run_service.RUN_STATUSES} 之一")
    return run_service.list_runs(
        session, status=status, agent_id=agent_id,
        conversation_id=conversation_id, page=page, page_size=page_size,
    )


@router.get("/{run_id}")
def get_run_detail(run_id: str, session: Session = Depends(get_session)):
    """运行详情：摘要 + 结构性事件时间线（默认不含载荷，FR-018）。"""
    try:
        return run_service.get_run_detail(session, run_id)
    except run_service.RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{run_id}/payloads")
def list_run_payloads(run_id: str, session: Session = Depends(get_session)):
    """载荷元数据列表（不含 content，按需加载入口）。"""
    try:
        return run_service.list_payloads(session, run_id)
    except run_service.RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{run_id}/payloads/{payload_id}")
def get_run_payload(run_id: str, payload_id: int, session: Session = Depends(get_session)):
    """单条载荷全文（详细载荷唯一受控读取入口，FR-021）。"""
    try:
        return run_service.get_payload(session, run_id, payload_id)
    except run_service.RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

conversations_router = APIRouter(prefix="/api/conversations", tags=["runs"])


@conversations_router.get("/{conversation_id}/runs")
def list_conversation_runs(conversation_id: int, session: Session = Depends(get_session)):
    """会话维度最近运行（聊天页"运行记录"入口）。"""
    try:
        return run_service.list_conversation_runs(session, conversation_id)
    except run_service.ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@conversations_router.get("/{conversation_id}/run-replays")
def list_conversation_replays(conversation_id: int, session: Session = Depends(get_session)):
    """会话内全部已终态运行的回放条目（聊天页刷新后回显全过程，FR-006/010 延伸）。"""
    try:
        return run_service.list_conversation_replays(session, conversation_id)
    except run_service.ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

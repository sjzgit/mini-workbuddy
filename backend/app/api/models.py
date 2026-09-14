"""模型管理路由层（只做 HTTP 编排）。

契约主定义：specs/002-model-management/contracts/api-contract.md
错误统一 {"detail": 人话信息}，永不包含密钥正文与堆栈（FR-011）。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.schemas.model import (
    DeleteResponse,
    ModelDetail,
    ModelItem,
    ModelUpsertRequest,
    SetDefaultResponse,
    TestConnectionResult,
)
from app.services import model_service
from app.services.agent_references import ReferencedByAgentError
from app.services.model_service import DefaultSwitchError, ModelNotFoundError

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=list[ModelItem])
def list_models(session: Session = Depends(get_session)) -> object:
    return model_service.list_models(session)


@router.get("/{model_id}", response_model=ModelDetail)
def get_model(model_id: int, session: Session = Depends(get_session)) -> object:
    try:
        return model_service.get_model(session, model_id)
    except ModelNotFoundError as exc:
        raise HTTPException(status_code=404, detail="模型不存在") from exc


@router.post("", response_model=ModelDetail, status_code=status.HTTP_201_CREATED)
def create_model(payload: ModelUpsertRequest, session: Session = Depends(get_session)) -> object:
    return model_service.create_model(session, payload)


@router.put("/{model_id}", response_model=ModelDetail)
def update_model(
    model_id: int,
    payload: ModelUpsertRequest,
    session: Session = Depends(get_session),
) -> object:
    try:
        return model_service.update_model(session, model_id, payload)
    except ModelNotFoundError as exc:
        raise HTTPException(status_code=404, detail="模型不存在") from exc


@router.delete("/{model_id}", response_model=DeleteResponse)
def delete_model(
    model_id: int,
    new_default_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
) -> DeleteResponse:
    try:
        model_service.delete_model(session, model_id, new_default_id)
        return DeleteResponse()
    except ModelNotFoundError as exc:
        raise HTTPException(status_code=404, detail="模型不存在") from exc
    except ReferencedByAgentError as exc:
        raise HTTPException(status_code=409, detail={
            "detail": str(exc),
            "referenced_by_agents": exc.referenced_by,
        }) from exc
    except DefaultSwitchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{model_id}/default", response_model=SetDefaultResponse)
def set_default(model_id: int, session: Session = Depends(get_session)) -> SetDefaultResponse:
    try:
        model_service.set_default(session, model_id)
        return SetDefaultResponse(id=model_id)
    except ModelNotFoundError as exc:
        raise HTTPException(status_code=404, detail="模型不存在") from exc


@router.post("/{model_id}/test-connection", response_model=TestConnectionResult)
def test_connection(model_id: int, session: Session = Depends(get_session)) -> object:
    try:
        return model_service.test_connection(session, model_id)
    except ModelNotFoundError as exc:
        raise HTTPException(status_code=404, detail="模型不存在") from exc

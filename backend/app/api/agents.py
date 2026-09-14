"""Agent 管理 API 路由（契约实现）。

契约主定义：specs/007-agent-management/contracts/agents-api.md
路由层薄：异常 → HTTP 状态映射 + 调 service。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.schemas.agents import (
    AgentDetail,
    AgentListItem,
    AgentOption,
    AgentSaveRequest,
    BindingOptionsResponse,
    DeleteResponse,
    ReferencedByAgentBody,
    RequiresNewDefaultBody,
)
from app.services import agent_service
from app.services.agent_service import (
    AgentNameConflictError,
    AgentNotFoundError,
    AgentValidationError,
    RequiresNewDefaultError,
)

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("", response_model=list[AgentListItem])
def list_agents(session: Session = Depends(get_session)) -> object:
    return agent_service.list_agents(session)


@router.get("/binding-options", response_model=BindingOptionsResponse)
def binding_options(
    agent_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
) -> BindingOptionsResponse:
    tools, skills, mcp_servers, models, prompt_template = agent_service.get_binding_options(
        session, agent_id,
    )
    return BindingOptionsResponse(
        tools=tools,
        skills=skills,
        mcp_servers=mcp_servers,
        models=models,
        prompt_template=prompt_template,
    )


@router.get("/{agent_id}", response_model=AgentDetail)
def get_agent(agent_id: int, session: Session = Depends(get_session)) -> object:
    try:
        return agent_service.get_agent(session, agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent 不存在") from exc


@router.post("", response_model=AgentDetail, status_code=status.HTTP_201_CREATED)
def create_agent(payload: AgentSaveRequest, session: Session = Depends(get_session)) -> object:
    try:
        return agent_service.save_agent(session, payload, None)
    except AgentNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/{agent_id}", response_model=AgentDetail)
def update_agent(
    agent_id: int,
    payload: AgentSaveRequest,
    session: Session = Depends(get_session),
) -> object:
    try:
        return agent_service.save_agent(session, payload, agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent 不存在") from exc
    except AgentNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{agent_id}", response_model=DeleteResponse)
def delete_agent(
    agent_id: int,
    new_default_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
) -> object:
    try:
        cleared_default = agent_service.delete_agent(session, agent_id, new_default_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent 不存在") from exc
    except RequiresNewDefaultError as exc:
        body = RequiresNewDefaultBody(
            candidates=exc.candidates,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=body.model_dump(),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DeleteResponse(cleared_default=cleared_default)


@router.post("/{agent_id}/default")
def set_default(agent_id: int, session: Session = Depends(get_session)) -> dict[str, int]:
    try:
        agent_service.set_default(session, agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent 不存在") from exc
    return {"id": agent_id}

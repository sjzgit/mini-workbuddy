"""MCP 管理路由层（只做 HTTP 编排）。

契约主定义：specs/004-skills-mcp-management/contracts/mcp-api.md
错误统一 {"detail": 人话信息}；任何响应不含 env/headers 明文与密文（FR-023）。
test 端点为 async（底层 SDK 客户端是 async，research R3）。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.schemas.mcp import (
    McpDeletedResponse,
    McpServerDetail,
    McpServerItem,
    McpServerUpsertRequest,
    McpTestResult,
    McpToggleRequest,
)
from app.services import mcp_service
from app.services.agent_references import ReferencedByAgentError
from app.services.mcp_service import McpBusyError, McpNameConflictError, McpNotFoundError

router = APIRouter(prefix="/api/mcp/servers", tags=["mcp"])


@router.get("", response_model=list[McpServerItem])
def list_servers(session: Session = Depends(get_session)) -> object:
    return mcp_service.list_servers(session)


@router.post("", response_model=McpServerDetail, status_code=201)
def create_server(payload: McpServerUpsertRequest, session: Session = Depends(get_session)) -> object:
    try:
        return mcp_service.create_server(session, payload)
    except McpNameConflictError as exc:
        raise HTTPException(status_code=400, detail=f"已存在同名 Server「{payload.name}」") from exc


@router.get("/{server_id}", response_model=McpServerDetail)
def get_server(server_id: int, session: Session = Depends(get_session)) -> object:
    try:
        return mcp_service.get_server(session, server_id)
    except McpNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MCP Server 不存在") from exc


@router.put("/{server_id}", response_model=McpServerDetail)
def update_server(
    server_id: int, payload: McpServerUpsertRequest, session: Session = Depends(get_session),
) -> object:
    try:
        return mcp_service.update_server(session, server_id, payload)
    except McpNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MCP Server 不存在") from exc
    except McpNameConflictError as exc:
        raise HTTPException(status_code=400, detail=f"已存在同名 Server「{payload.name}」") from exc
    except McpBusyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{server_id}", response_model=McpDeletedResponse)
def delete_server(server_id: int, session: Session = Depends(get_session)) -> object:
    try:
        mcp_service.delete_server(session, server_id)
    except ReferencedByAgentError as exc:
        raise HTTPException(status_code=409, detail={
            "detail": str(exc),
            "referenced_by_agents": exc.referenced_by,
        }) from exc
    except McpNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MCP Server 不存在") from exc
    except McpBusyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return McpDeletedResponse()


@router.put("/{server_id}/enabled", response_model=McpServerItem)
def set_server_enabled(
    server_id: int, payload: McpToggleRequest, session: Session = Depends(get_session),
) -> object:
    try:
        return mcp_service.set_enabled(session, server_id, payload.enabled)
    except McpNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MCP Server 不存在") from exc


@router.post("/{server_id}/test", response_model=McpTestResult)
async def test_server(server_id: int, session: Session = Depends(get_session)) -> object:
    """测试连接（US6）：async——底层为 MCP SDK 的 async 客户端。"""
    try:
        return await mcp_service.test_server(session, server_id)
    except McpNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MCP Server 不存在") from exc
    except McpBusyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

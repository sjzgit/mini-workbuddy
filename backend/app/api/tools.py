"""工具管理路由层（只做 HTTP 编排）。

契约主定义：specs/003-tool-management/contracts/api-contract.md
本模块只提供列表 / 详情 / 启停三个端点——系统内置工具不允许删除或修改用途
（FR-007），因此没有 DELETE 与其他 PUT 端点；统一执行入口为进程内服务
tool_executor（research R6），不经 HTTP 暴露。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.schemas.tool import ToolDetail, ToolItem, ToolToggleRequest
from app.services import tool_service
from app.services.tool_service import ToolNotFoundError

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("", response_model=list[ToolItem])
def list_tools(session: Session = Depends(get_session)) -> object:
    return tool_service.list_tools(session)


@router.get("/{name}", response_model=ToolDetail)
def get_tool(name: str, session: Session = Depends(get_session)) -> object:
    try:
        return tool_service.get_tool(session, name)
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=404, detail="工具不存在") from exc


@router.put("/{name}/enabled", response_model=ToolItem)
def set_tool_enabled(
    name: str,
    payload: ToolToggleRequest,
    session: Session = Depends(get_session),
) -> object:
    try:
        return tool_service.set_enabled(session, name, payload.enabled)
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=404, detail="工具不存在") from exc

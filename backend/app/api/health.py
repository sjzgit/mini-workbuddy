"""健康检查路由。

执行一次数据库探测（SELECT 1）验证应用与数据库连接均可用。
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.schemas.health import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(session: Session = Depends(get_session)) -> Response:
    """探测应用存活与数据库连通性。"""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "detail": "database unavailable"},
        )
    return Response(
        status_code=200,
        media_type="application/json",
        content=HealthResponse(status="ok").model_dump_json(),
    )

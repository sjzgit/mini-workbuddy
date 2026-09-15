"""FastAPI 应用入口。

启动：uv run python start_dev.py（在 backend/ 目录执行；--reset 可清理端口残留进程）
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import agents, chat, health, mcp, models, skills, tools
from app.core.config import settings

# 日志配置：uvicorn 只接管自己的 logger，root 无 handler 且默认 WARNING，
# 业务日志（含 LLM API 调用日志，FR-011）必须显式放开到 INFO。
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
logging.getLogger("app").setLevel(logging.INFO)

app = FastAPI(title=settings.app_name)
app.include_router(health.router)
app.include_router(models.router)
app.include_router(tools.router)
app.include_router(skills.router)
app.include_router(mcp.router)
app.include_router(agents.router)
app.include_router(chat.router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _request: Request, exc: RequestValidationError,
) -> JSONResponse:
    """422 统一为 {"detail": 人话信息}（契约约定），不含堆栈与内部细节。"""
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    # pydantic 的 "Value error, xxx" 前缀对人无意义，剥掉
    message = str(first.get("msg", "参数校验失败")).removeprefix("Value error, ")
    prefix = f"{location}：" if location else ""
    return JSONResponse(status_code=422, content={"detail": f"{prefix}{message}"})

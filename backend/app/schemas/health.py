"""健康检查契约实现。

契约主定义：specs/001-project-init/contracts/api-contract.md
本文件字段与类型 MUST 与契约一致。
"""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """GET /api/health 响应体。"""

    model_config = {"json_schema_extra": {"required": ["status"]}}

    status: Literal["ok", "unhealthy"]
    detail: str | None = Field(default=None, exclude=True)

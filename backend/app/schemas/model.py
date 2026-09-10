"""模型管理契约实现。

契约主定义：specs/002-model-management/contracts/api-contract.md
本文件字段与类型 MUST 与契约一致。响应模型永不含密钥正文（只有 api_key_configured）。
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

# ---- 常量（契约主定义，实现侧只消费）----
TEMPERATURE_MIN = 0.0
TEMPERATURE_MAX = 2.0
TEST_CONNECTION_TIMEOUT_SECONDS = 30.0
TEST_CONNECTION_MAX_TOKENS = 64
TEST_CONNECTION_PROMPT = "你好，请用一句话回复：连接成功"
REPLY_EXCERPT_MAX_CHARS = 200

TestErrorCategory = Literal[
    "auth_error",
    "model_not_found",
    "unreachable",
    "timeout",
    "bad_response",
    "unknown",
]


class ModelItem(BaseModel):
    """列表项（GET /api/models）。"""

    id: int
    display_name: str
    model_identifier: str
    base_url: str
    context_length: int
    api_key_configured: bool
    is_default: bool
    updated_at: str  # ISO 8601


class ModelDetail(ModelItem):
    """详情（新增/编辑/详情响应），在列表项之上补充可编辑字段。"""

    max_output_tokens: int
    temperature: Decimal
    input_price: Decimal | None
    output_price: Decimal | None
    cached_input_price: Decimal | None

    @field_serializer("temperature", "input_price", "output_price", "cached_input_price")
    @classmethod
    def serialize_decimal(cls, value: Decimal | None) -> float | None:
        """契约约定价格/温度为 JSON number（未配置输出 null）。"""
        return None if value is None else float(value)


class ModelUpsertRequest(BaseModel):
    """新增/编辑提交体（校验规则见 data-model.md 校验规则 1–5）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    display_name: str = Field(min_length=1, max_length=100)
    model_identifier: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str | None = None  # None/空 = 保留原密钥（编辑）；非空 = 替换
    context_length: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    temperature: Decimal = Field(ge=TEMPERATURE_MIN, le=TEMPERATURE_MAX)
    input_price: Decimal | None = Field(default=None, ge=0)
    output_price: Decimal | None = Field(default=None, ge=0)
    cached_input_price: Decimal | None = Field(default=None, ge=0)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        """http/https 合法 URL，且不得以 /chat/completions 结尾（误填拦截）。"""
        if not value.startswith(("http://", "https://")):
            raise ValueError("服务地址必须以 http:// 或 https:// 开头")
        host_part = value.split("://", 1)[1]
        if "/" not in host_part and "." not in host_part:
            raise ValueError("服务地址格式不正确，请填写完整地址")
        if value.rstrip("/").lower().endswith("/chat/completions"):
            raise ValueError(
                "无需填写到 /chat/completions，只填 API Base URL（一般以 /v1 结尾）",
            )
        return value.rstrip("/")

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str | None) -> str | None:
        """空白密钥视为未填写（保留原密钥）。"""
        if value is not None and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_token_budget(self) -> "ModelUpsertRequest":
        """跨字段：最大输出长度不得超过上下文长度（FR-007）。"""
        if self.max_output_tokens > self.context_length:
            raise ValueError("最大输出长度不能超过上下文长度")
        return self


class DeleteResponse(BaseModel):
    """DELETE /api/models/{id} 响应。"""

    deleted: bool = True


class SetDefaultResponse(BaseModel):
    """POST /api/models/{id}/default 响应。"""

    id: int
    is_default: bool = True


class TestConnectionResult(BaseModel):
    """POST /api/models/{id}/test-connection 响应。"""

    success: bool
    category: TestErrorCategory | None = None
    message: str
    reply_excerpt: str | None = None

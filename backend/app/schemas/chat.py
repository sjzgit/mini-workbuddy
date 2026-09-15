"""聊天功能 Pydantic Schema（API 契约实现）。

契约主定义：specs/008-chat-conversations/contracts/chat-api.md
字段与校验 MUST 与契约逐条对齐，变更先改契约。
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ---- 常量（契约"枚举与常量"节的主定义落点）----

RoleLiteral = Literal["user", "assistant"]

MessageStatusLiteral = Literal["generating", "completed", "incomplete"]

StreamErrorCategoryLiteral = Literal[
    "unreachable",
    "timeout",
    "auth_error",
    "model_not_found",
    "bad_response",
    "empty_response",
    "stream_interrupted",
    "context_overflow",
    "unknown",
]

TITLE_DEFAULT = "新会话"
TITLE_MAX_CHARS = 20
MESSAGE_MAX_CHARS = 32000
CONTEXT_CHAR_TOKEN_RATIO = 0.6
STREAM_PING_INTERVAL_SECONDS = 15

# 上下文超限 422 文案（契约错误响应约定节，前端原样展示）
CONTEXT_OVERFLOW_DETAIL = (
    "会话历史过长，已超出该模型可用的上下文容量。请缩短输入或新建会话。"
)


class ConversationSummary(BaseModel):
    """会话摘要（列表项 / 新建、切换返回；列表只返回摘要，FR-006）。"""

    id: int
    title: str
    agent_id: int
    updated_at: str
    created_at: str


class MessageOut(BaseModel):
    """消息（读取与流终态事件返回）。"""

    id: int
    conversation_id: int
    role: RoleLiteral
    agent_id: int | None = None
    agent_name: str | None = None
    reasoning_content: str | None = None
    content: str
    status: MessageStatusLiteral
    seq: int
    created_at: str


class SendMessageRequest(BaseModel):
    """发送消息请求体：去首尾空白后 1~32000 字符。"""

    content: str = Field(min_length=1, max_length=MESSAGE_MAX_CHARS)

    @model_validator(mode="after")
    def _normalize(self) -> "SendMessageRequest":
        stripped = self.content.strip()
        if not stripped:
            raise ValueError("消息内容不能为空")
        self.content = stripped
        return self


class SwitchAgentRequest(BaseModel):
    """切换会话 Agent 请求体。"""

    agent_id: int


class StartReplyResponse(BaseModel):
    """发送 / 重新生成的 201 响应（契约 StartReplyResponse）。"""

    user_message: MessageOut | None = None
    reply_message_id: int
    conversation: ConversationSummary


class StopResponse(BaseModel):
    """停止响应：恒 stopped=true，终态以流事件或消息行为准。"""

    stopped: bool = True


# ---- SSE 事件 data 结构（契约 StreamEvent 节）----


class ReasoningDeltaData(BaseModel):
    """event: reasoning_delta。"""

    text: str


class ContentDeltaData(BaseModel):
    """event: content_delta。"""

    text: str


class DoneEventData(BaseModel):
    """event: done：终态消息（已完成 / incomplete）已落库。"""

    message: MessageOut | None = None  # 占位行被删除时为 null（停止/失败且无正文）
    stopped: bool = False


class ErrorEventData(BaseModel):
    """event: error：人话文案直接可展示，不含敏感信息。"""

    category: StreamErrorCategoryLiteral
    message: str

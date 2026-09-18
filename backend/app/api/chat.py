"""聊天 API 路由（契约实现）。

契约主定义：specs/008-chat-conversations/contracts/chat-api.md
路由层薄：异常 → HTTP 状态映射 + 调 service；生成任务在异步路由内启动。
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.schemas.chat import (
    AskAnswerRequest,
    AskAnswerResponse,
    ConversationSummary,
    MessageOut,
    SendMessageRequest,
    StartReplyResponse,
    StopResponse,
    SwitchAgentRequest,
)
from app.services import chat_service, workspace_service
from app.services.agent_runtime.ask_user import submit_answer
from app.services.generation_registry import get_registry
from app.services.chat_service import (
    AgentUnavailableError,
    ConversationBusyError,
    ConversationNotFoundError,
    ContextOverflowError,
    MessageNotFoundError,
    RegenerateInvalidError,
)
from app.services.workspace_service import WorkspaceError, WorkspaceSetRequest

router = APIRouter(prefix="/api/conversations", tags=["chat"])

_MSG_404_CONVERSATION = "会话不存在"
_MSG_404_MESSAGE = "消息不存在"


def _to_http_error(exc: Exception) -> HTTPException:
    """服务异常 → HTTP 状态（400/404/409/422，契约错误响应约定节）。"""
    if isinstance(exc, MessageNotFoundError):
        return HTTPException(status_code=404, detail=_MSG_404_MESSAGE)
    if isinstance(exc, ConversationNotFoundError):
        return HTTPException(status_code=404, detail=_MSG_404_CONVERSATION)
    if isinstance(exc, LookupError):
        # workspace_service 的会话不存在（LookupError 子类语义同 404）
        return HTTPException(status_code=404, detail=_MSG_404_CONVERSATION)
    if isinstance(exc, WorkspaceError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, AgentUnavailableError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, ConversationBusyError | RegenerateInvalidError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ContextOverflowError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="服务器内部错误")



@router.get("", response_model=list[ConversationSummary])
def list_conversations(session: Session = Depends(get_session)) -> object:
    return chat_service.list_conversations(session)


@router.post("", response_model=ConversationSummary, status_code=201)
def create_conversation_route(
    payload: SwitchAgentRequest,
    session: Session = Depends(get_session),
) -> object:
    try:
        return chat_service.create_conversation(session, payload.agent_id)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc


@router.put("/{conversation_id}", response_model=ConversationSummary)
def switch_agent_route(
    conversation_id: int,
    payload: SwitchAgentRequest,
    session: Session = Depends(get_session),
) -> object:
    try:
        return chat_service.switch_agent(session, conversation_id, payload.agent_id)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc



@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def get_messages_route(
    conversation_id: int,
    session: Session = Depends(get_session),
) -> object:
    try:
        return chat_service.get_messages(session, conversation_id)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc


# ---- 014：Session Workspace（契约 workspace-permission-api.md §1；busy 允许切换）----


@router.get("/{conversation_id}/workspace")
def get_workspace_route(
    conversation_id: int,
    session: Session = Depends(get_session),
) -> object:
    try:
        return workspace_service.get_workspace(session, conversation_id)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc


@router.put("/{conversation_id}/workspace")
def set_workspace_route(
    conversation_id: int,
    payload: WorkspaceSetRequest,
    session: Session = Depends(get_session),
) -> object:
    try:
        return workspace_service.set_workspace(session, conversation_id, payload.path)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc


@router.delete("/{conversation_id}/workspace")
def clear_workspace_route(
    conversation_id: int,
    session: Session = Depends(get_session),
) -> object:
    try:
        return workspace_service.clear_workspace(session, conversation_id)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc


@router.post("/{conversation_id}/messages", response_model=StartReplyResponse, status_code=201)
async def send_message_route(
    conversation_id: int,
    payload: SendMessageRequest,
    session: Session = Depends(get_session),
) -> object:
    try:
        return chat_service.send_message(session, conversation_id, payload)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc



@router.get("/{conversation_id}/messages/{message_id}/stream")
async def stream_message_route(
    conversation_id: int,
    message_id: int,
    session: Session = Depends(get_session),
) -> object:
    try:
        chat_service.get_message(session, conversation_id, message_id)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc
    return StreamingResponse(
        chat_service.build_message_stream(session, conversation_id, message_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{conversation_id}/messages/{message_id}/ask-answers", response_model=AskAnswerResponse)
async def ask_answers_route(
    conversation_id: int,
    message_id: int,
    payload: AskAnswerRequest,
    session: Session = Depends(get_session),
) -> AskAnswerResponse:
    """提交 ask_user 的回答：唤醒挂起的运行，回答作为工具结果交还模型（契约 §3）。"""
    try:
        chat_service.get_message(session, conversation_id, message_id)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc
    # 生成已终态（迟到回答）→ 409；空回答 → 422；call_id 未命中挂起 → 404（契约 §3）
    task = get_registry().get(message_id)
    if task is None or task.terminal_event is not None:
        raise HTTPException(status_code=409, detail="生成已结束，回答未被接受")
    if not payload.selected and not (payload.text or "").strip():
        raise HTTPException(status_code=422, detail="回答不能为空")
    if not submit_answer(payload.call_id, payload.selected, payload.text):
        raise HTTPException(status_code=404, detail="没有等待回答的询问，可能已超时或已完成")
    return AskAnswerResponse(resolved=True)


@router.post("/{conversation_id}/messages/{message_id}/stop", response_model=StopResponse)
async def stop_message_route(
    conversation_id: int,
    message_id: int,
    session: Session = Depends(get_session),
) -> object:
    try:
        chat_service.get_message(session, conversation_id, message_id)
        await chat_service.stop_generation(conversation_id, message_id)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc
    return StopResponse(stopped=True)



@router.post("/{conversation_id}/regenerate", response_model=StartReplyResponse, status_code=201)
async def regenerate_route(
    conversation_id: int,
    session: Session = Depends(get_session),
) -> object:
    try:
        return chat_service.regenerate(session, conversation_id)
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc

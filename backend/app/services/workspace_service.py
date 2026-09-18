"""会话工作空间管理（specs/014-workspace-permission，research R7；data-model §1.1）。

WorkspaceManager 三职责：查询 / 设置（校验 + 持久化）/ 清除。
校验：绝对路径 → 可解析 → 存在且是目录 → 非系统保护路径（设置时即拒绝，
运行时 PermissionManager 兜底）。**不做 busy 检查**：AgentRun 启动时已快照，
运行中切换只影响后续运行（spec 二十八）。
运行时权限判定不在此处（唯一入口 = agent_runtime.permission.PermissionManager）。
"""

import logging
from datetime import datetime, timezone

from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models import ConversationEntry

logger = logging.getLogger(__name__)

SOURCE_USER_SELECTED = "user_selected"

# 契约 §1.2 错误文案（api 层 400 detail 原样展示）
MSG_REQUIRES_ABSOLUTE = "请提供绝对路径（如 D:\\projects\\demo）"


class WorkspaceError(ValueError):
    """工作空间校验失败（路由层转 400，message = 人话 detail）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ConversationWorkspaceOut(BaseModel):
    """GET/PUT/DELETE workspace 的统一响应（契约 §1.1；三字段均可空 = 未选择）。"""

    workspace_path: str | None = None
    workspace_source: str | None = None
    workspace_selected_at: str | None = None


class WorkspaceSetRequest(BaseModel):
    """PUT workspace 请求体（契约 §1.2）。"""

    path: str

    def model_post_init(self, _ctx) -> None:  # noqa: ANN001 — pydantic v2 钩子
        self.path = self.path.strip()


def _to_out(entry: ConversationEntry) -> ConversationWorkspaceOut:
    return ConversationWorkspaceOut(
        workspace_path=entry.workspace_path,
        workspace_source=entry.workspace_source,
        workspace_selected_at=(
            entry.workspace_selected_at.isoformat()
            if entry.workspace_selected_at is not None
            else None
        ),
    )


def _get_or_404(session: Session, conversation_id: int) -> ConversationEntry:
    entry = session.get(ConversationEntry, conversation_id)
    if entry is None:
        raise LookupError(f"会话 {conversation_id} 不存在")
    return entry


def get_workspace(session: Session, conversation_id: int) -> ConversationWorkspaceOut:
    """查询当前会话工作空间（未选择时三字段 None）。"""
    return _to_out(_get_or_404(session, conversation_id))


def set_workspace(
    session: Session, conversation_id: int, raw_path: str,
) -> ConversationWorkspaceOut:
    """设置/更换会话工作空间：校验 → 规范化持久化（source=USER_SELECTED）。"""
    entry = _get_or_404(session, conversation_id)
    path_str = (raw_path or "").strip()
    if not path_str:
        raise WorkspaceError(MSG_REQUIRES_ABSOLUTE)

    from app.services.agent_runtime.permission import (
        default_protected,
        is_within,
        resolve_path,
    )

    candidate = Path(path_str)
    if not candidate.is_absolute():
        raise WorkspaceError(MSG_REQUIRES_ABSOLUTE)
    try:
        resolved = resolve_path(path_str)
    except OSError as exc:
        raise WorkspaceError(f"工作空间路径无法解析：{path_str}") from exc
    if not resolved.exists():
        raise WorkspaceError(f"工作空间路径不存在：{path_str}")
    if not resolved.is_dir():
        raise WorkspaceError(f"工作空间路径不是目录：{path_str}")
    for protected in default_protected():
        if is_within(resolved, protected):
            raise WorkspaceError(
                f"该路径为系统保护路径，不允许设为工作空间：{path_str}",
            )

    old_path = entry.workspace_path
    entry.workspace_path = str(resolved)
    entry.workspace_source = SOURCE_USER_SELECTED
    entry.workspace_selected_at = datetime.now(timezone.utc).replace(
        tzinfo=None, microsecond=0,
    )
    session.commit()
    logger.info(
        "[workspace] 会话 %s 工作空间变更：%s → %s（user_selected）",
        conversation_id, old_path, resolved,
    )
    return _to_out(entry)


def clear_workspace(session: Session, conversation_id: int) -> ConversationWorkspaceOut:
    """清除会话工作空间（三列置 NULL 单事务；未设置时幂等成功）。"""
    entry = _get_or_404(session, conversation_id)
    old_path = entry.workspace_path
    entry.workspace_path = None
    entry.workspace_source = None
    entry.workspace_selected_at = None
    session.commit()
    if old_path:
        logger.info(
            "[workspace] 会话 %s 工作空间清除（原值 %s）", conversation_id, old_path,
        )
    return _to_out(entry)

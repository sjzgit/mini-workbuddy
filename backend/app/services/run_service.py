"""运行记录查询服务（specs/011，契约 runs-api.md）。

列表恒定 2 条 SQL（COUNT + SELECT，SC-003）；全部展示字段来自 runs 行快照，
无逐行关联查询（FR-013）。
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ConversationEntry, RunEntry, RunEventEntry, RunPayloadEntry

# runs.status 枚举（契约 runs-api.md 唯一主定义）
RUN_STATUS_RUNNING = "running"
RUN_STATUS_SUCCEEDED = "succeeded"
RUN_STATUS_PARTIAL = "partial"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_CANCELLED = "cancelled"

RUN_STATUSES = (
    RUN_STATUS_RUNNING, RUN_STATUS_SUCCEEDED, RUN_STATUS_PARTIAL,
    RUN_STATUS_FAILED, RUN_STATUS_CANCELLED,
)

INTERRUPTED_REASON = "运行中断：服务在运行期间重启"


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def mark_interrupted_runs(session: Session) -> int:
    """启动恢复（FR-007）：running → failed 并注明"运行中断"。返回处理条数。"""
    rows = session.scalars(
        select(RunEntry).where(RunEntry.status == RUN_STATUS_RUNNING)
    ).all()
    for row in rows:
        row.status = RUN_STATUS_FAILED
        row.end_reason = INTERRUPTED_REASON
        row.error_category = row.error_category or "unknown"
        finished = _utcnow()
        row.finished_at = finished
        if row.started_at is not None:
            row.total_duration_ms = int((finished - row.started_at).total_seconds() * 1000)
    if rows:
        session.commit()
    # 状态快照一致性：running 仅在真有任务时存在（FR-009）
    return len(rows)


def _to_summary(row: RunEntry):
    """runs 行 → RunSummary（契约 runs-api.md）。"""
    from app.schemas.runs import RunSummary

    return RunSummary(
        run_id=row.run_id,
        conversation_id=row.conversation_id,
        agent_name=row.agent_name,
        model_name=row.model_name,
        workspace_path=getattr(row, "workspace_path", None),
        status=row.status,
        end_reason=row.end_reason,
        error_summary=row.error_summary,
        started_at=row.started_at.isoformat(),
        finished_at=row.finished_at.isoformat() if row.finished_at else None,
        total_duration_ms=row.total_duration_ms,
        model_call_count=row.model_call_count,
        tool_call_count=row.tool_call_count,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        total_tokens=row.total_tokens,
        first_output_ms=row.first_output_ms,
    )


def list_runs(
    session: Session,
    *,
    status: str | None = None,
    agent_id: int | None = None,
    conversation_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
):
    """运行列表（SC-003：恒定 2 条 SQL；快照字段无关联查询）。"""
    from app.schemas.runs import PAGE_DEFAULT, PAGE_SIZE_DEFAULT, PAGE_SIZE_MAX, RunListResponse

    page = max(1, page)
    page_size = min(max(1, page_size), PAGE_SIZE_MAX)
    conditions = []
    if status:
        conditions.append(RunEntry.status == status)
    if agent_id is not None:
        conditions.append(RunEntry.agent_id == agent_id)
    if conversation_id is not None:
        conditions.append(RunEntry.conversation_id == conversation_id)
    total = session.scalar(select(func.count(RunEntry.id)).where(*conditions)) or 0
    rows = session.scalars(
        select(RunEntry)
        .where(*conditions)
        .order_by(RunEntry.started_at.desc(), RunEntry.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return RunListResponse(
        items=[_to_summary(row) for row in rows],
        total=total, page=page, page_size=page_size,
    )


class RunNotFoundError(LookupError):
    """运行记录不存在（路由层转 404）。"""


def get_run_detail(session: Session, run_id: str):
    """运行详情：摘要 + 全部结构性事件（单查询，FR-018 不含载荷）。"""
    from app.schemas.runs import RunDetailResponse, RunEventOut

    row = session.scalar(select(RunEntry).where(RunEntry.run_id == run_id))
    if row is None:
        raise RunNotFoundError("运行记录不存在")
    events = session.scalars(
        select(RunEventEntry).where(RunEventEntry.run_id == run_id).order_by(RunEventEntry.seq)
    ).all()
    return RunDetailResponse(
        summary=_to_summary(row),
        events=[
            RunEventOut(
                seq=e.seq, event_type=e.event_type, round=e.round,
                call_id=e.call_id, data=e.data or {},
                created_at=e.created_at.isoformat(),
            )
            for e in events
        ],
    )


def list_payloads(session: Session, run_id: str):
    """载荷元数据列表（不含 content，FR-018）。"""
    from app.schemas.runs import RunPayloadMeta

    _require_run(session, run_id)
    rows = session.scalars(
        select(RunPayloadEntry).where(RunPayloadEntry.run_id == run_id).order_by(RunPayloadEntry.id)
    ).all()
    return [
        RunPayloadMeta(id=r.id, call_id=r.call_id, payload_type=r.payload_type, char_count=r.char_count)
        for r in rows
    ]


def get_payload(session: Session, run_id: str, payload_id: int):
    """单条载荷全文（唯一读取入口，FR-021）。"""
    from app.schemas.runs import RunPayloadContent

    _require_run(session, run_id)
    row = session.get(RunPayloadEntry, payload_id)
    if row is None or row.run_id != run_id:
        raise RunNotFoundError("载荷不存在")
    return RunPayloadContent(
        id=row.id, call_id=row.call_id, payload_type=row.payload_type,
        char_count=row.char_count, content=row.content,
    )


class ConversationNotFoundError(LookupError):
    """会话不存在（路由层转 404）。"""


def list_conversation_runs(session: Session, conversation_id: int, limit: int = 20):
    """会话维度最近运行（聊天页入口）。"""
    if session.get(ConversationEntry, conversation_id) is None:
        raise ConversationNotFoundError("会话不存在")
    rows = session.scalars(
        select(RunEntry)
        .where(RunEntry.conversation_id == conversation_id)
        .order_by(RunEntry.started_at.desc(), RunEntry.id.desc())
        .limit(limit)
    ).all()
    return [_to_summary(row) for row in rows]


def _require_run(session: Session, run_id: str) -> None:
    if session.scalar(select(RunEntry.id).where(RunEntry.run_id == run_id)) is None:
        raise RunNotFoundError("运行记录不存在")


# ---- 会话消息过程回放（011 优化①：刷新后回显工具调用全过程）----

# 回放条目类型：reasoning / content / tool（与前端 StreamSegment 对应）
_REPLAY_RUN_STATUSES = ("succeeded", "partial", "failed", "cancelled")


def build_run_replay(session: Session, row: RunEntry) -> dict:
    """把一次运行的结构性事件 + 载荷重建成有序回放条目。

    条目按事件 seq 排列，天然还原"轮内文本 → 工具卡片 → 下一轮文本"的交错序；
    正文/思考来自 model_output 载荷（JSON：content/reasoning/tool_calls；
    旧数据为纯文本时降级为 content）；工具卡片含完整参数与结果文本。
    """
    import json as _json

    from app.schemas.runs import RunStatusLiteral  # noqa: F401（语义标注用）

    events = session.scalars(
        select(RunEventEntry).where(RunEventEntry.run_id == row.run_id).order_by(RunEventEntry.seq)
    ).all()
    payloads = session.scalars(
        select(RunPayloadEntry).where(RunPayloadEntry.run_id == row.run_id)
    ).all()
    payload_map: dict[tuple[str, str], str] = {
        (p.call_id, p.payload_type): p.content for p in payloads
    }

    items: list[dict] = []

    def _parse_output(call_id: str) -> tuple[str | None, str | None]:
        raw = payload_map.get((call_id, "model_output"))
        if not raw:
            return (None, None)
        try:
            obj = _json.loads(raw)
        except ValueError:
            return (None, raw)  # 旧格式：纯文本降级
        if isinstance(obj, dict):
            return (obj.get("reasoning"), obj.get("content"))
        return (None, raw)

    def _payload_text(call_id: str, payload_type: str) -> str:
        return payload_map.get((call_id, payload_type), "")

    for event in events:
        data = event.data or {}
        if event.event_type == "model_request_completed" and data.get("purpose") == "chat":
            reasoning, content = _parse_output(event.call_id or "")
            if reasoning:
                items.append({"kind": "reasoning", "round": event.round, "text": reasoning})
            if content:
                items.append({"kind": "content", "round": event.round, "text": content})
        elif event.event_type == "tool_call_completed":
            started = next(
                (e for e in events
                 if e.event_type == "tool_call_started" and e.call_id == event.call_id),
                None,
            )
            items.append({
                "kind": "tool",
                "round": event.round,
                "callId": event.call_id,
                "toolName": data.get("tool_name", ""),
                "displayName": (started or event).data.get("display_name") or data.get("tool_name", ""),
                "toolType": data.get("tool_type", "builtin"),
                "serverName": (started or event).data.get("server_name"),
                "status": data.get("status", "success"),
                "durationMs": data.get("duration_ms"),
                "paramsSummary": (started or event).data.get("params_summary", ""),
                "resultSummary": data.get("result_summary", ""),
                "paramsText": _payload_text(event.call_id or "", "tool_params"),
                "resultText": _payload_text(event.call_id or "", "tool_result"),
            })
    return {
        "run_id": row.run_id,
        "reply_message_id": row.reply_message_id,
        "status": row.status,
        "items": items,
    }


def list_conversation_replays(session: Session, conversation_id: int) -> list[dict]:
    """会话内全部已终态运行的回放（聊天页刷新后回显全过程，按开始时间倒序）。"""
    rows = session.scalars(
        select(RunEntry)
        .where(
            RunEntry.conversation_id == conversation_id,
            RunEntry.reply_message_id.is_not(None),
            RunEntry.status.in_(_REPLAY_RUN_STATUSES),
        )
        .order_by(RunEntry.started_at.desc(), RunEntry.id.desc())
        .limit(50)
    ).all()
    return [build_run_replay(session, row) for row in rows]

"""RunRecorder：运行记录持久化（specs/011 FR-001~009、FR-043~045）。

在 execute_run 内消费真实事件流，依据事件落库三张表：
runs（一行一运行，快照+聚合指标）、run_events（结构性事件，幂等）、
run_payloads（详细载荷，脱敏后完整保存，不截断）。
增量事件不落库（011 澄清决定），仅用于 first_output_ms 计算。
"""

import json
import logging
import time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.models import AgentEntry, ModelEntry, RunEntry, RunEventEntry, RunPayloadEntry
from app.schemas.agent_runtime import (
    EVENT_ASK_USER,
    EVENT_PERMISSION_CHECKED,
    EVENT_COMPRESSION_COMPLETED,
    EVENT_COMPRESSION_FAILED,
    EVENT_COMPRESSION_FALLBACK,
    EVENT_COMPRESSION_STARTED,
    EVENT_CONTENT_DELTA,
    EVENT_ERROR,
    EVENT_MODEL_REQUEST_COMPLETED,
    EVENT_MODEL_REQUEST_STARTED,
    EVENT_REASONING_DELTA,
    EVENT_RUN_COMPLETED,
    EVENT_RUN_STARTED,
    EVENT_TOOL_CALL_COMPLETED,
    EVENT_TOOL_CALL_STARTED,
)
from app.services.sanitize import sanitize_messages, sanitize_text

logger = logging.getLogger(__name__)

# 落库前从事件 data 中剥离的字段（透传字段 + 010 展示字段；FR-044：事件只留安全摘要）
_EVENT_DATA_STRIP_KEYS = frozenset({
    "content_text", "reasoning_text",
    "params_full", "result_full", "request_messages",
    "output_content", "output_reasoning", "output_tool_calls", "output_full",
    "input_full", "params", "result",
})

# runs.status 映射（契约 runs-api.md；data-model §8.1）
_STATUS_MAP = {
    "completed": "succeeded",
    "max_rounds": "partial",
    "error": "failed",
    "cancelled": "cancelled",
}

# 工具调用计数口径（FR-014）：denied=校验拒绝，不计入已执行
_TOOL_COUNTED_STATUSES = frozenset({"success", "error", "cancelled"})

# 终态兜底文案（CancelledError / GeneratorExit 路径）
REASON_FALLBACK_CANCELLED = "运行被用户取消"
REASON_FALLBACK_BROKEN = "运行中断：记录未正常收尾"


class RunRecorder:
    """按事件增量持久化一次运行。由 execute_run 创建与驱动；内部异常全部吞掉。"""

    def __init__(
        self,
        run_id: str,
        *,
        conversation_id: int | None = None,
        reply_message_id: int | None = None,
        agent_id: int | None = None,
    ) -> None:
        self.run_id = run_id
        self._conversation_id = conversation_id
        self._reply_message_id = reply_message_id
        self._agent_id = agent_id
        self._row_created = False
        self._mono_start: float | None = None
        self._model_call_count = 0
        self._tool_call_count = 0
        self._usage = None
        self._first_output_ms: int | None = None
        self._last_error: tuple[str, str] | None = None
        self._finished = False

    # ---- 公开入口 ----

    def observe(self, event) -> None:
        """消费一条事件（透传原事件）。内部异常吞掉：记录失败不影响运行。"""
        try:
            self._observe(event)
        except Exception:  # noqa: BLE001
            logger.warning(
                "[recorder] run %s 事件落库失败 event=%s", self.run_id, event.event,
                exc_info=True,
            )

    def finish(self, *, cancelled: bool = False, reason: str = "") -> None:
        """无终态事件路径的终态兜底（CancelledError / GeneratorExit）。"""
        if self._finished:
            return
        self._finished = True
        try:
            self._persist_finish(
                status="cancelled" if cancelled else "failed",
                end_reason=reason or REASON_FALLBACK_CANCELLED,
                error_category=None if cancelled else "unknown",
                error_summary=None if cancelled else (reason or REASON_FALLBACK_BROKEN),
            )
        except Exception:  # noqa: BLE001
            logger.warning("[recorder] run %s 终态兜底失败", self.run_id, exc_info=True)

    def close(self) -> None:
        """安全网：全部退出路径后若仍未收尾，按失败处理。"""
        self.finish(cancelled=False, reason="运行中断：记录未正常收尾")

    # ---- 事件分发 ----

    def _observe(self, event) -> None:
        name = event.event
        if name == EVENT_RUN_STARTED:
            self._ensure_row(
                agent_name=str(event.data.get("agent_name", "")),
                model_name=str(event.data.get("model_name", "")),
                model_identifier=str(event.data.get("model_identifier", "")),
                workspace_path=event.data.get("workspace_path"),
            )
            self._insert_event(event)
            return
        if name == EVENT_CONTENT_DELTA and str(event.data.get("text", "")):
            if self._first_output_ms is None and self._mono_start is not None:
                self._first_output_ms = self._now_ms()
            return
        if name in (EVENT_REASONING_DELTA,):
            return
        if name == EVENT_MODEL_REQUEST_STARTED:
            self._ensure_row()
            self._model_call_count += 1
            self._insert_event(event)
            return
        if name == EVENT_MODEL_REQUEST_COMPLETED:
            self._merge_usage(event.data.get("usage"))
            req = event.data.get("request_messages")
            if req is not None:
                payload = json.dumps(req, ensure_ascii=False, indent=2, default=str)
                self._save_payload(str(event.data["call_id"]), "model_input", payload)
            if (event.data.get("output_content") is not None
                    or event.data.get("output_reasoning") is not None
                    or event.data.get("output_tool_calls") is not None):
                out_obj = {
                    "content": event.data.get("output_content"),
                    "reasoning": event.data.get("output_reasoning"),
                    "tool_calls": event.data.get("output_tool_calls"),
                }
                self._save_payload(
                    str(event.data["call_id"]), "model_output",
                    json.dumps(out_obj, ensure_ascii=False, indent=2, default=str),
                )
            self._insert_event(event)
            return
        if name == EVENT_TOOL_CALL_STARTED:
            params_full = str(event.data.get("params_full", ""))
            if params_full:
                self._save_payload(str(event.data["call_id"]), "tool_params", params_full)
            self._insert_event(event)
            return
        if name == EVENT_TOOL_CALL_COMPLETED:
            if event.data.get("status") in _TOOL_COUNTED_STATUSES:
                self._tool_call_count += 1
            result_full = str(event.data.get("result_full", ""))
            if result_full:
                self._save_payload(str(event.data["call_id"]), "tool_result", result_full)
            self._insert_event(event)
            return
        if name == EVENT_ASK_USER:
            # 013：询问事件作为结构性事件落 run_events（FR-016 可回看）；
            # 回答内容经对应 tool_call_completed 的 tool_result payload 完整保存
            self._insert_event(event)
            return
        if name == EVENT_PERMISSION_CHECKED:
            # 014：权限判定事件落 run_events（US5 审计：工具/路径/决策/原因，
            # 负载天然无文件内容——FR-033）
            self._insert_event(event)
            return
        if name in (EVENT_COMPRESSION_STARTED, EVENT_COMPRESSION_COMPLETED,
                    EVENT_COMPRESSION_FAILED, "compression_fallback"):
            if name == EVENT_COMPRESSION_STARTED:
                input_full = str(event.data.get("input_full", ""))
                if input_full:
                    self._save_payload(str(event.call_id or ""), "compression_input", input_full)
            if name == EVENT_COMPRESSION_COMPLETED:
                output_full = str(event.data.get("output_full", ""))
                if output_full:
                    self._save_payload(str(event.call_id or ""), "compression_output", output_full)
            self._insert_event(event)
            return
        if name == EVENT_ERROR:
            category = str(event.data.get("category", "unknown"))
            message = sanitize_text(str(event.data.get("message", "")))[:500]
            self._last_error = (category, message)
            self._insert_event(event)
            return
        if name == EVENT_RUN_COMPLETED:
            self._insert_event(event)
            self._persist_finish_from_completed(event.data)
            return
        # 未知事件类型：忽略（前向兼容）
        return

    # ---- 辅助 ----

    def _now_ms(self) -> int:
        if self._mono_start is None:
            return 0
        return int((time.monotonic() - self._mono_start) * 1000)

    def _ensure_row(
        self,
        agent_name: str = "",
        model_name: str = "",
        model_identifier: str = "",
        workspace_path: str | None = None,
    ) -> None:
        """首事件时创建 runs 行（status=running，快照字段）。"""
        if self._row_created:
            return
        self._row_created = True
        self._mono_start = time.monotonic()
        if not agent_name or not model_name:
            # run_started 之前先出错等路径：从库中补快照
            info = self._lookup_agent_model()
            agent_name = agent_name or info[0]
            model_name = model_name or info[1]
            model_identifier = model_identifier or info[2]
        with SessionLocal() as session:
            session.add(RunEntry(
                run_id=self.run_id,
                conversation_id=self._conversation_id,
                reply_message_id=self._reply_message_id,
                agent_id=self._agent_id,
                agent_name=agent_name,
                model_name=model_name,
                model_identifier=model_identifier,
                workspace_path=workspace_path,  # 014：运行启动时快照（Invariant 6）
                status="running",
            ))
            session.commit()

    def _lookup_agent_model(self) -> tuple[str, str, str]:
        """按 agent_id 从库中补快照（run_started 未到时的兜底）。"""
        if self._agent_id is None:
            return ("", "", "")
        with SessionLocal() as session:
            agent = session.get(AgentEntry, self._agent_id)
            if agent is None:
                return ("", "", "")
            model = session.get(ModelEntry, agent.model_id)
            if model is None:
                return (agent.name, "", "")
            return (agent.name, model.display_name, model.model_identifier)

    def _merge_usage(self, usage: dict | None) -> None:
        """把单次请求用量并入累计（任一未知则该项未知，FR-034/015）。"""
        if usage is None:
            return
        from app.schemas.agent_runtime import UsageInfo

        incoming = UsageInfo(
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
        self._usage = (
            incoming if self._usage is None else self._usage.merge_add(incoming)
        )

    def _save_payload(self, call_id: str, payload_type: str, content: str) -> None:
        """载荷脱敏后完整保存（unique(run_id,call_id,type) 冲突时跳过）。"""
        from app.core.config import settings

        workspace = settings.authorized_dir
        content = sanitize_text(content, workspace_prefix=workspace) if payload_type not in (
            "model_input",
        ) else sanitize_text(json.dumps(sanitize_messages(json.loads(content)), ensure_ascii=False, default=str), workspace_prefix=workspace)
        with SessionLocal() as session:
            session.add(RunPayloadEntry(
                run_id=self.run_id, call_id=call_id,
                payload_type=payload_type, content=content,
                char_count=len(content),
            ))
            session.commit()

    def _insert_event(self, event) -> None:
        """插入结构性事件（unique(run_id,seq) 冲突跳过 = 重复投递幂等，FR-008）。"""
        if not self._row_created:
            self._ensure_row()
        data = {k: v for k, v in event.data.items() if k not in _EVENT_DATA_STRIP_KEYS}
        with SessionLocal() as session:
            session.add(RunEventEntry(
                run_id=self.run_id, seq=event.seq,
                event_type=event.event, round=event.round,
                call_id=event.call_id, data=data,
            ))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()  # 重复投递：跳过（FR-008）

    def _persist_finish_from_completed(self, data: dict) -> None:
        """按 run_completed 事件数据收尾 runs 行（恰一次）。"""
        if self._finished:
            return
        self._finished = True
        runtime_status = str(data.get("status", "error"))
        usage_total = data.get("usage_total")
        if usage_total is not None:
            self._merge_usage(usage_total)  # usage_total 与逐请求求和口径一致（取已知项之和）
        self._persist_finish(
            status=_STATUS_MAP.get(runtime_status, "failed"),
            end_reason=str(data.get("reason", "")),
            error_category=self._last_error[0] if self._last_error else None,
            error_summary=self._last_error[1] if self._last_error else None,
        )

    def _persist_finish(
        self,
        *,
        status: str,
        end_reason: str,
        error_category: str | None,
        error_summary: str | None,
    ) -> None:
        """终态 UPDATE runs 行（幂等：已收尾则忽略）。"""
        if not self._row_created:
            self._ensure_row()
        duration = self._now_ms()
        with SessionLocal() as session:
            row = session.scalar(
                select(RunEntry).where(RunEntry.run_id == self.run_id)
            )
            if row is None:
                return
            row.status = status
            row.end_reason = (end_reason or "")[:500]
            row.error_category = error_category
            row.error_summary = error_summary
            row.finished_at = _utcnow()
            row.total_duration_ms = duration
            row.model_call_count = self._model_call_count
            row.tool_call_count = self._tool_call_count
            row.first_output_ms = self._first_output_ms
            if self._usage is not None:
                row.prompt_tokens = self._usage.prompt_tokens
                row.completion_tokens = self._usage.completion_tokens
                row.total_tokens = self._usage.total_tokens
            session.commit()


def _utcnow():
    """与 models._utcnow 同口径：naive UTC、去微秒。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

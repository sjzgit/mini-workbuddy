"""运行内工具目录、命名映射与统一执行入口（specs/009-agent-runtime 契约 §4）。

命名规则：内置=注册表原名；MCP=mcp__{消毒Server名}__{原名}（冲突追加 _2/_3…）；
load_skill 为保留名（仅存在可用 Skill 时提供）。执行入口永不抛异常，
失败也是结构化返回交还模型。
013 增补：ask_user 挂起等待语义（specs/013-ask-user-tool research R1）。
014 增补：权限检查阶段（file_read_write / shell 分发前统一三值判定，
specs/014-workspace-permission；ASK_USER 复用 013 挂起机制，US3）。
"""

import asyncio
import json
import logging
import re
import time
import uuid
from pathlib import Path
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AgentBinding, McpServerEntry, SkillEntry, ToolEntry
from app.schemas.mcp import McpToolInfo
from app.schemas.agent_runtime import EVENT_PERMISSION_CHECKED
from app.services import mcp_client, skill_files

if TYPE_CHECKING:
    from app.services.agent_runtime import RunLimits, RunRequest
    from app.services.agent_runtime.ask_user import PendingAsk
    from app.services.agent_runtime.events import RunEventEmitter
    from app.services.agent_runtime.permission import (
        PermissionDecision,
        RunPermissionContext,
    )

logger = logging.getLogger(__name__)

# 工具类型（契约 §4）
TOOL_TYPE_BUILTIN = "builtin"
TOOL_TYPE_MCP = "mcp"
TOOL_TYPE_SKILL = "skill"

# load_skill 暴露名与参数 JSON Schema（契约 §5）
LOAD_SKILL_NAME = "load_skill"
LOAD_SKILL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "skill_id": {"type": "string", "description": "Skill 稳定标识（目录名）"},
    },
    "required": ["skill_id"],
}

# MCP 失败错误码（契约 §4）
MCP_ERROR = "mcp_error"

_MCP_NAME_MAX = 64

# ---- 014：权限确认选项与路径提取（契约 workspace-permission-api.md §2.3/§4.2）----

PERMISSION_ALLOW_LABEL = "允许本次访问"
PERMISSION_DENY_LABEL = "拒绝"

# shell 命令文本中可明确解析出的绝对路径形态（Windows 盘符 / POSIX 绝对路径）。
# 仅提取"明确写出的路径参数"做检查（契约 §4.2：应用层检查边界，不做命令解析沙箱）
_SHELL_PATH_PATTERN = re.compile(
    r"[A-Za-z]:[\\/][^\s\"'|;&<>]*"
    r"|(?<=\s)/(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+"
)


@dataclass
class ToolCatalogEntry:
    """暴露给模型的单个工具目录项（data-model.md §1.5）。"""

    exposed_name: str
    tool_type: str  # builtin | mcp | skill
    description: str | None
    parameters: dict[str, Any]
    ref: str  # 内置=注册表 name；MCP=原始工具名；skill=dir_name
    server_id: int | None = None


@dataclass
class ToolCallRecord:
    """一次工具调用的运行期记录（data-model.md §1.7；010 增补展示字段）。"""

    call_id: str
    exposed_name: str
    tool_type: str = TOOL_TYPE_BUILTIN
    ref: str = ""
    status: str = ""  # success | error | denied | cancelled | pending_ask（瞬态）
    result_for_model: str = ""
    summary: str = ""
    params_summary: str = ""
    duration_ms: int = 0
    started_at_seq: int = 0
    ended_at_seq: int = 0
    # ---- 010 增补（工具过程卡片展示，specs/010-tool-execution-display/data-model.md §2.1）----
    params_full: str = ""  # 原始参数文本（事件 params 字段来源，产出前再截断）
    result_full: str = ""  # 完整结果文本：成功=交还模型全文；失败=人话原因（无堆栈）
    display_name: str = ""  # 易读名称（卡片标题主体，FR-003）
    server_name: str | None = None  # MCP Server 显示名，仅 mcp 非空
    # ---- 013 增补：ask_user 挂起信息（非 None 时主循环发 ask_user 事件并等待）----
    ask: "AskPendingInfo | None" = None
    # ---- 014 增补：权限确认挂起扩展（US3；非 None 时回答后驱动 grant/拒绝）----
    permission: "PermissionAskInfo | None" = None
    # ---- 014 增补：权限判定事件暂存（run_tool 非生成器无法产出，主循环取用）----
    pending_events: list = field(default_factory=list)


@dataclass
class AskPendingInfo:
    """一次挂起中的 ask_user 询问（run_tool 注册、主循环等待，specs/013 research R1）。"""

    pending: "PendingAsk"
    question: str
    options: list[str]
    multi_select: bool
    started_mono: float  # 时长口径与 _finish_record 一致（monotonic 起点）


@dataclass
class PermissionAskInfo:
    """权限确认挂起的扩展信息（记录在 ToolCallRecord.permission；014 US3）。

    允许 → grant 追加 + 原工具调用重执行；拒绝/超时/取消 → 结构化失败。
    """

    tool_ref: str  # file_read_write | shell
    arguments: dict[str, Any]  # 原始工具参数（allow 后重执行用）
    resolved_paths: list[str]  # 触发 ask 的规范化路径（str(Path)）
    base_reason: str  # 首个 ask_user 路径的判定原因（question 文案来源）


@dataclass
class ToolCallOutcome:
    """工具执行产物（Runtime 内部统一形态）。"""

    success: bool
    result_for_model: str = ""
    summary: str = ""
    error_code: str | None = None
    message: str | None = None


@dataclass
class ToolContext:
    """运行内工具上下文：目录、映射、MCP 会话表、取消事件与请求引用。"""

    run_request: "RunRequest"
    emitter: "RunEventEmitter"
    cancel: asyncio.Event
    catalog: dict[str, ToolCatalogEntry] = field(default_factory=dict)
    skill_catalog_ids: frozenset[str] = frozenset()
    mcp_sessions: dict[int, Any] = field(default_factory=dict)  # server_id → ClientSession
    mcp_stacks: dict[int, AsyncExitStack] = field(default_factory=dict)
    # ---- 014 增补：运行权限上下文（启动快照；None = 跳过权限检查）----
    permission: "RunPermissionContext | None" = None


# ---- 命名与 Schema 助手 ----


def sanitize_mcp_name(name: str) -> str:
    """非 [A-Za-z0-9_-] 折叠为 _，截断到 64（契约 §4 消毒规则）。"""
    sanitized = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    return sanitized[:_MCP_NAME_MAX]


def _unique_name(name: str, used: set[str]) -> str:
    """暴露名去重：冲突追加 _2、_3…（契约 §4）。"""
    if name not in used:
        return name
    n = 2
    while f"{name}_{n}" in used:
        n += 1
    return f"{name}_{n}"


def _schema_from_params_model(model: type) -> dict[str, Any]:
    """内置工具参数模型 → 函数参数 JSON Schema（去掉 title，禁多余参数）。"""
    schema = dict(model.model_json_schema())
    schema.pop("title", None)
    schema.pop("$defs", None)
    schema["additionalProperties"] = False
    return schema


def _mcp_param_schema(tool: McpToolInfo, snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """MCP 工具参数 Schema：优先 tools_json 快照中的原始 inputSchema。"""
    raw = (snapshot or {}).get("input_schema")
    if isinstance(raw, dict) and raw.get("type") == "object":
        return raw
    # 快照无原始 Schema 时从参数表重建（宽松 object，类型按名称映射）
    type_map = {
        "string": "string", "number": "number", "integer": "integer",
        "boolean": "boolean", "array": "array", "object": "object",
    }
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in tool.params:
        properties[param.name] = {
            "type": type_map.get(param.type, "string"),
            "description": param.description,
        }
        if param.required:
            required.append(param.name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


async def _connect_one(
    session: Session, entry: McpServerEntry,
) -> tuple[Any, AsyncExitStack, list[McpToolInfo]]:
    """连接单个 Server：stdio/http 传输 → initialize → list_tools。

    任何失败向上抛异常（由 connect_mcp_servers 统一分类记日志）；
    失败路径自行关栈，不留子进程残留。
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import get_default_environment, stdio_client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    from app.services.mcp_service import _load_secrets

    stack = AsyncExitStack()
    try:
        if entry.server_type == "stdio":
            env, _headers = _load_secrets(session, entry)
            env_base = get_default_environment()
            env_base.update(env or {})
            params = StdioServerParameters(
                command=entry.command or "",
                args=list(entry.command_args or []),
                env=env_base,
            )
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(params),
            )
        else:
            _env, headers = _load_secrets(session, entry)
            http_client = (
                create_mcp_http_client(headers=headers or None)
                if headers else None
            )
            streams = await stack.enter_async_context(
                streamable_http_client(entry.url or "", http_client=http_client),
            )
            read_stream, write_stream = streams[0], streams[1]
        mcp_session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream),
        )
        await mcp_session.initialize()
        result = await mcp_session.list_tools()
        tools = [
            McpToolInfo(name=t.name, description=t.description or "", params=[])
            for t in result.tools
        ]
        return mcp_session, stack, tools
    except BaseException:
        # 覆盖超时/取消注入：退出必须与进入同 task（anyio cancel scope 归属），
        # 清理失败不掩盖原始异常（FR-029 尽力清理）
        try:
            await stack.aclose()
        except BaseException:  # noqa: BLE001 — 清理失败不掩盖原始异常
            logger.warning("[runtime] MCP 连接失败清理异常", exc_info=True)
        raise


async def connect_mcp_servers(
    session: Session, server_ids: list[int],
) -> tuple[
    dict[int, Any],
    dict[int, AsyncExitStack],
    dict[int, list[McpToolInfo]],
]:
    """为绑定且启用的 MCP Server 逐个连接并 list_tools（超时不阻断运行）。

    返回 (server_id → ClientSession, server_id → ExitStack, server_id → 工具列表)。
    连接失败：记日志跳过，该 Server 工具不进目录；模型若点名调用将得到 mcp_error
    （研究 R5：连接失败不阻断运行）。
    """
    sessions: dict[int, Any] = {}
    stacks: dict[int, AsyncExitStack] = {}
    tools_by_server: dict[int, list[McpToolInfo]] = {}
    for server_id in server_ids:
        entry = session.get(McpServerEntry, server_id)
        if entry is None or not entry.enabled:
            continue
        try:
            # asyncio.timeout（而非 wait_for）：不换 Task，保证 stdio_client 的
            # anyio cancel scope 进入/退出同 task（修复 RuntimeError: Attempted
            # to exit a cancel scope that isn't the current task's ...）
            async with asyncio.timeout(settings.runtime_mcp_connect_timeout_seconds):
                mcp_session, stack, tools = await _connect_one(session, entry)
        except TimeoutError:
            logger.warning(
                "[runtime] MCP Server %s(%s) 连接超时（%s 秒），本次运行跳过",
                server_id, entry.name, settings.runtime_mcp_connect_timeout_seconds,
            )
            continue
        except Exception as exc:  # noqa: BLE001 — 单 Server 失败不阻断运行（R5）
            logger.warning(
                "[runtime] MCP Server %s(%s) 连接失败：%s", server_id, entry.name, exc,
            )
            continue
        sessions[server_id] = mcp_session
        stacks[server_id] = stack
        tools_by_server[server_id] = tools
    return sessions, stacks, tools_by_server


def build_tool_catalog(
    session: Session,
    agent_id: int,
    limits: "RunLimits | None" = None,
) -> tuple[list[ToolCatalogEntry], frozenset[str]]:
    """构建本次运行的工具目录：绑定 ∩ 启用（再经 limits 收窄）。

    返回 (目录条目列表, 可加载 skill_id 集合)。limits 只能收窄（FR-003）。
    """
    from app.services.agent_runtime import RunLimits
    from app.services.tool_registry import all_definitions

    limits = limits or RunLimits()

    used: set[str] = set()
    catalog: list[ToolCatalogEntry] = []
    skill_ids: set[str] = set()

    # ---- 内置工具：绑定 × tools.enabled ----
    rows = session.execute(
        select(ToolEntry.name, ToolEntry.enabled)
        .join(AgentBinding, (AgentBinding.resource_id == ToolEntry.id) & (AgentBinding.resource_type == "tool"))
        .where(AgentBinding.agent_id == agent_id)
    ).all()
    definitions = {d.name: d for d in all_definitions()}
    for name, enabled in rows:
        if not enabled:
            continue
        definition = definitions.get(name)
        if definition is None:
            continue
        exposed = _unique_name(name, used)
        used.add(exposed)
        catalog.append(ToolCatalogEntry(
            exposed_name=exposed,
            tool_type=TOOL_TYPE_BUILTIN,
            description=definition.purpose,
            parameters=_schema_from_params_model(definition.params_model),
            ref=name,
        ))

    # ---- MCP 工具：绑定 × mcp_servers.enabled，按 tools_json 快照展开 ----
    servers = session.execute(
        select(McpServerEntry)
        .join(AgentBinding, (AgentBinding.resource_id == McpServerEntry.id) & (AgentBinding.resource_type == "mcp"))
        .where(AgentBinding.agent_id == agent_id, McpServerEntry.enabled == True)  # noqa: E712
    ).scalars().all()
    for server in servers:
        snapshot = mcp_client.loads_tools(server.tools_json)
        for tool in snapshot:
            exposed = _unique_name(
                f"mcp__{sanitize_mcp_name(server.name)}__{tool.name}", used,
            )
            used.add(exposed)
            catalog.append(ToolCatalogEntry(
                exposed_name=exposed,
                tool_type=TOOL_TYPE_MCP,
                description=tool.description,
                parameters=_mcp_param_schema(tool, None),
                ref=tool.name,
                server_id=server.id,
            ))

    # ---- Skill：绑定 × skills.enabled → XML 目录 + load_skill 工具 ----
    skill_rows = session.execute(
        select(SkillEntry)
        .join(AgentBinding, (AgentBinding.resource_id == SkillEntry.id) & (AgentBinding.resource_type == "skill"))
        .where(AgentBinding.agent_id == agent_id, SkillEntry.enabled == True)  # noqa: E712
    ).scalars().all()
    for skill in skill_rows:
        if skill.dir_name in limits.disabled_skill_ids:
            continue
        skill_ids.add(skill.dir_name)
    if skill_ids:
        exposed = _unique_name(LOAD_SKILL_NAME, used)
        used.add(exposed)
        catalog.append(ToolCatalogEntry(
            exposed_name=exposed,
            tool_type=TOOL_TYPE_SKILL,
            description="读取指定 Skill 的完整指令。仅当任务符合某 Skill 用途时调用。",
            parameters=LOAD_SKILL_PARAMETERS,
            ref=exposed,
        ))

    # ---- limits 白名单收窄（FR-003：只能收窄）----
    if limits.allowed_tool_names is not None:
        allowed = set(limits.allowed_tool_names)
        catalog = [entry for entry in catalog if entry.exposed_name in allowed]
        skill_ids = set()  # limits 收窄工具目录时按白名单语义收窄 skill（保守处理）

    return catalog, frozenset(skill_ids)


def _summary(text: str) -> str:
    """脱敏摘要：截断到 settings.runtime_tool_result_summary_chars（FR-037）。"""
    text = text or ""
    limit = settings.runtime_tool_result_summary_chars
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _finish_record(
    record: ToolCallRecord,
    outcome: ToolCallOutcome,
    *,
    status: str,
    started: float,
    started_at_seq: int,
    params_summary: str,
) -> ToolCallRecord:
    """把执行产物写入记录（状态/摘要/耗时/事件序号）。"""
    record.status = status
    if params_summary:
        record.params_summary = params_summary
    record.result_for_model = outcome.result_for_model or _failure_result_text(outcome)
    record.result_full = record.result_for_model
    record.summary = outcome.summary or _summary(outcome.message or outcome.result_for_model or "")
    record.duration_ms = int((time.monotonic() - started) * 1000)
    record.started_at_seq = started_at_seq
    return record


def _failure_result_text(outcome: ToolCallOutcome) -> str:
    """失败时交还模型的文本（错误码 + 人话信息）。"""
    parts = []
    if outcome.error_code:
        parts.append(f"[{outcome.error_code}]")
    if outcome.message:
        parts.append(outcome.message)
    return " ".join(parts) or "工具执行失败"


def _display_info(entry: ToolCatalogEntry, session: Session) -> tuple[str, str | None]:
    """解析卡片易读标题（010 契约 §1.1）：builtin=注册表 display_name；
    mcp=原工具名 + Server 显示名；skill=固定"加载 Skill"。"""
    if entry.tool_type == TOOL_TYPE_BUILTIN:
        from app.services.tool_registry import get_definition

        definition = get_definition(entry.ref)
        return (definition.display_name if definition else entry.ref), None
    if entry.tool_type == TOOL_TYPE_MCP:
        server = session.get(McpServerEntry, entry.server_id) if entry.server_id is not None else None
        return entry.ref, (server.name if server else None)
    return "加载 Skill", None


# ---- 014：权限检查阶段（specs/014-workspace-permission，research R2；Invariant 2/9）----


def _permission_targets(
    tool_ref: str, arguments: dict[str, Any],
) -> list[str]:
    """从工具参数中提取需要判定的路径（原始字符串形式）。

    file_read_write：path 参数（相对或绝对）。
    shell：显式 cwd 参数 + 命令文本中可明确解析的绝对路径
    （契约 §4.2：应用层检查边界——间接访问不做检查，如实声明非沙箱）。
    """
    targets: list[str] = []
    if tool_ref == "file_read_write":
        path = str(arguments.get("path", "")).strip()
        if path:
            targets.append(path)
    elif tool_ref == "shell":
        cwd = str(arguments.get("cwd", "")).strip()
        if cwd:
            targets.append(cwd)
        command = str(arguments.get("command", ""))
        for match in _SHELL_PATH_PATTERN.findall(command):
            if match:
                targets.append(match)
    return targets


def _permission_denied_decision(raw: str) -> "PermissionDecision":
    """解析失败 → DENY(path_resolution_failed)（FR-051：内部错误不放行）。"""
    from app.services.agent_runtime.permission import DECISION_DENY, PermissionDecision

    return PermissionDecision(
        decision=DECISION_DENY,
        path=raw,
        reason=f"路径无法解析：{raw}",
        error_code="path_resolution_failed",
    )


def _emit_permission_checked(
    record: ToolCallRecord, ctx: "ToolContext", call_id: str,
    tool_name: str, decision: "PermissionDecision",
) -> None:
    """产出一条 permission_checked 事件（US5；含 allow——审计覆盖每次判定，SC-008）。

    run_tool 非生成器无法直接产出：事件先暂存 record.pending_events，
    由主循环在 tool_call_started 之后 yield（seq 已由 emitter 分配，顺序稳定）。
    """
    from app.schemas.agent_runtime import PermissionCheckedData

    data = PermissionCheckedData(
        round=0,  # 审计事件不轮绑：运行记录经 call_id 关联工具调用
        call_id=call_id, decision=decision.decision, tool_name=tool_name,
        path=decision.path, reason=decision.reason,
    )
    record.pending_events.append(ctx.emitter.emit(
        EVENT_PERMISSION_CHECKED, data,
        round=0, call_id=call_id,
    ))


def _run_permission_stage(
    tool_ref: str,
    arguments: dict[str, Any],
    call_id: str,
    record: ToolCallRecord,
    ctx: "ToolContext",
) -> "tuple[AskPendingInfo, PermissionAskInfo] | None":
    """权限检查阶段主判定（014；判定顺序 = data-model §3 状态机）。

    返回 None = 无需挂起（全 allow → 继续分发；有 deny → 已发事件，调用方收尾）；
    返回 (AskPendingInfo, PermissionAskInfo) = ASK_USER 挂起（复用 013 机制）。
    """
    from app.services.agent_runtime import ask_user as ask_registry
    from app.services.agent_runtime.permission import (
        DECISION_ASK_USER,
        DECISION_DENY,
        PermissionManager,
        resolve_path,
    )

    assert ctx.permission is not None
    targets = _permission_targets(tool_ref, arguments)
    base = Path(ctx.permission.session_root or ctx.permission.system_root)
    resolved: list[Path] = []
    decisions: list = []
    ask_decisions: list = []
    for raw in targets:
        try:
            resolved_path = resolve_path(raw, base=base)
        except OSError:
            decisions.append(_permission_denied_decision(raw))
            continue
        resolved.append(resolved_path)
        decision = PermissionManager.check(resolved_path, ctx.permission)
        decisions.append(decision)
        if decision.decision == DECISION_ASK_USER:
            ask_decisions.append(decision)

    # ① 有 deny（保护集/解析失败）：全部路径发事件 → 调用方结构化失败
    if any(d.decision == DECISION_DENY for d in decisions):
        for decision in decisions:
            _emit_permission_checked(record, ctx, call_id, tool_ref, decision)
        return None

    # ② 有 ASK_USER：全部路径发事件 → 挂起（问题文案 = 契约 §2.3）
    if ask_decisions:
        for decision in decisions:
            _emit_permission_checked(record, ctx, call_id, tool_ref, decision)
        first_ask = ask_decisions[0]
        if len(ask_decisions) > 1:
            question = (
                "Agent 请求访问会话工作空间之外的路径："
                + "、".join(d.path for d in ask_decisions)
                + f"（原因：{first_ask.reason}）。是否允许本次运行访问？"
            )
        else:
            question = (
                f"Agent 请求访问会话工作空间之外的路径：{first_ask.path}"
                f"（原因：{first_ask.reason}）。是否允许本次运行访问？"
            )
        pending = ask_registry.register(call_id)
        ask_info = AskPendingInfo(
            pending=pending,
            question=question,
            options=[PERMISSION_ALLOW_LABEL, PERMISSION_DENY_LABEL],
            multi_select=False,
            started_mono=time.monotonic(),
        )
        permission_info = PermissionAskInfo(
            tool_ref=tool_ref,
            arguments=arguments,
            resolved_paths=[str(p) for p in resolved],
            base_reason=first_ask.reason,
        )
        return ask_info, permission_info

    # ③ 全 allow（含 grant 命中）：发事件后继续分发
    for decision in decisions:
        _emit_permission_checked(record, ctx, call_id, tool_ref, decision)
    return None


def _permission_deny_outcome(
    tool_ref: str, arguments: dict[str, Any], ctx: "ToolContext",
) -> ToolCallOutcome | None:
    """无挂起路径的 deny 收尾：重新判定取首个 deny（错误码 + 人话原因）。"""
    from app.services.agent_runtime.permission import (
        DECISION_DENY,
        PermissionManager,
        resolve_path,
    )

    assert ctx.permission is not None
    targets = _permission_targets(tool_ref, arguments)
    base = Path(ctx.permission.session_root or ctx.permission.system_root)
    for raw in targets:
        try:
            resolved_path = resolve_path(raw, base=base)
        except OSError:
            return ToolCallOutcome(
                success=False, error_code="path_resolution_failed",
                message=f"路径无法解析：{raw}",
            )
        decision = PermissionManager.check(resolved_path, ctx.permission)
        if decision.decision == DECISION_DENY:
            return ToolCallOutcome(
                success=False,
                error_code=decision.error_code or "permission_check_failed",
                message=decision.reason,
            )
    return None


def _resolve_shell_cwd(arguments: dict[str, Any], permission: Any) -> str:
    """shell 执行基准目录：显式 cwd 参数（已过权限检查）> 会话工作空间 > 系统目录。"""
    explicit = str(arguments.get("cwd", "")).strip()
    if explicit:
        from app.services.agent_runtime.permission import resolve_path

        return str(resolve_path(explicit))
    root = permission.session_root or permission.system_root
    return str(root)


async def run_tool(
    exposed_name: str,
    raw_arguments: "dict[str, Any] | str",
    ctx: ToolContext,
    session: Session,
) -> ToolCallRecord:
    """统一执行入口：目录查名 → 取消检查 → 权限检查 → 分发执行 → 记录（FR-022/023）。

    永不抛异常（asyncio.CancelledError 除外）；失败也是结构化记录交还模型。
    status: success | error | denied | cancelled。
    """
    from app.services.agent_runtime.skills import load_skill

    call_id = ctx.emitter.next_call_id("t")
    started = time.monotonic()
    started_at_seq = ctx.emitter._seq
    record = ToolCallRecord(call_id=call_id, exposed_name=exposed_name)
    raw_text = raw_arguments if isinstance(raw_arguments, str) else json.dumps(raw_arguments, ensure_ascii=False)
    record.params_full = raw_text
    params_summary = _summary(raw_text)
    outcome: ToolCallOutcome | None = None
    status = "error"

    try:
        if isinstance(raw_arguments, str):
            arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
        else:
            arguments = dict(raw_arguments)

        # 执行前取消检查
        if ctx.cancel.is_set():
            return _finish_record(record, ToolCallOutcome(
                success=False, error_code="cancelled", message="运行已取消，工具未执行",
            ), status="cancelled", started=started, started_at_seq=started_at_seq, params_summary=params_summary)

        # ① 目录内查名（不在目录 → denied；含幻觉名称/未绑定/limits 收窄掉的）
        entry = ctx.catalog.get(exposed_name)
        if entry is None:
            return _finish_record(record, ToolCallOutcome(
                success=False, error_code="tool_not_found",
                message=f"工具不存在或未在本次运行目录中：{exposed_name}",
            ), status="denied", started=started, started_at_seq=started_at_seq, params_summary=params_summary)

        record.tool_type = entry.tool_type
        record.ref = entry.ref
        record.display_name, record.server_name = _display_info(entry, session)

        # ①.5 权限检查阶段（014；仅 builtin 的 file_read_write / shell；
        # Invariant 2/9：运行时授权判定唯一入口；ctx.permission 为 None 时跳过）
        shell_cwd: str | None = None
        if (
            entry.tool_type == TOOL_TYPE_BUILTIN
            and entry.ref in ("file_read_write", "shell")
            and ctx.permission is not None
        ):
            if _permission_targets(entry.ref, arguments):
                stage_result = _run_permission_stage(entry.ref, arguments, call_id, record, ctx)
                if stage_result is not None:
                    # ASK_USER → 权限确认挂起（主循环发 ask_user 事件并等待）
                    ask_info, permission_info = stage_result
                    record.ask = ask_info
                    record.permission = permission_info
                    record.status = "pending_ask"
                    return record
                # 无挂起：deny → 结构化失败（重新判定取拒绝原因）
                deny_outcome = _permission_deny_outcome(entry.ref, arguments, ctx)
                if deny_outcome is not None:
                    return _finish_record(
                        record, deny_outcome, status="denied",
                        started=started, started_at_seq=started_at_seq,
                        params_summary=params_summary,
                    )
                # allow → shell 计算执行基准 cwd（显式参数 > 会话工作空间 > 系统目录）
                if entry.ref == "shell":
                    shell_cwd = _resolve_shell_cwd(arguments, ctx.permission)

        # ② 分发执行（各类型内部再做 DB 复核与参数校验）
        if entry.tool_type == TOOL_TYPE_SKILL:
            outcome = load_skill(session, ctx, str(arguments.get("skill_id", "")))
        elif entry.tool_type == TOOL_TYPE_BUILTIN and entry.ref == "ask_user":
            # ask_user 专用：校验参数 → 注册挂起 → 返回 pending 标记；
            # 实际等待在 runtime 主循环（发事件后 asyncio.wait，research R1）
            pending_outcome, ask_info = _begin_ask_user(arguments, call_id, ctx)
            if ask_info is None:
                outcome = pending_outcome
                status = "denied" if (pending_outcome.error_code or "") == "invalid_params" else "error"
            else:
                record.ask = ask_info
                record.status = "pending_ask"  # 瞬态：主循环等待后改写
                return record
        elif entry.tool_type == TOOL_TYPE_BUILTIN:
            outcome = _run_builtin(entry.ref, arguments, session, shell_cwd=shell_cwd)
        elif entry.tool_type == TOOL_TYPE_MCP:
            outcome = await _run_mcp(entry, arguments, ctx, session)
        else:  # pragma: no cover
            outcome = ToolCallOutcome(success=False, error_code="tool_not_found", message="未知工具类型")

        if outcome.success:
            status = "success"
        elif outcome.error_code == "cancelled":
            status = "cancelled"
        elif outcome.error_code and outcome.error_code.startswith("skill_"):
            status = "denied"
        elif entry.tool_type == TOOL_TYPE_BUILTIN and outcome.error_code in (
            "tool_not_found", "tool_disabled", "invalid_params",
        ):
            status = "denied"
        else:
            status = "error"

    except json.JSONDecodeError:
        outcome = ToolCallOutcome(
            success=False, error_code="invalid_params",
            message="工具参数不是合法 JSON：请检查 arguments 是否为对象",
        )
        status = "denied"
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — 兜底不抛（与 tool_executor 同哲学）
        logger.exception("[runtime] 工具 %s 执行异常", exposed_name)
        outcome = ToolCallOutcome(success=False, error_code="execution_error", message=f"工具执行出错：{exc}")
        status = "error"

    return _finish_record(
        record, outcome, status=status,
        started=started, started_at_seq=started_at_seq, params_summary=params_summary,
    )


def _run_builtin(
    name: str, arguments: dict[str, Any], session: Session,
    shell_cwd: str | None = None,
) -> ToolCallOutcome:
    """内置工具：委托 tool_executor.execute（启停/参数/危险命令校验都在其中）。"""
    from app.services.tool_executor import execute

    result = execute(name, arguments, session, shell_cwd=shell_cwd)
    if result.success:
        return ToolCallOutcome(
            success=True, result_for_model=result.output or "",
            summary=_summary(result.output or ""),
        )
    return ToolCallOutcome(
        success=False, error_code=result.error_code or "execution_error",
        message=result.message, summary=_summary(result.message or ""),
    )


# ---- 014：权限确认回答后的续行（US3；runtime 主循环 ask 分支调用）----


async def resume_pending_tool(
    record: ToolCallRecord,
    outcome: ToolCallOutcome,
    ctx: ToolContext,
    session: Session,
) -> ToolCallRecord:
    """ask 等待结束后的记录收尾：013 ask_user → 答案交还；014 权限确认 → grant/拒绝。

    权限分支：选中「允许本次访问」→ 为全部挂起路径创建 TemporaryGrant（仅当前
    运行）→ 重执行原工具调用（grant 已生效，直接分发不再走权限阶段）；
    拒绝/超时/取消 → permission_denied_by_user / cancelled 结构化失败。
    """
    ask = record.ask
    assert ask is not None
    permission_info = record.permission

    # 013 ask_user（无权限扩展）：保持原行为——答案文本交还模型
    if permission_info is None:
        return finish_ask_user_record(record, outcome)

    from app.services.agent_runtime.permission import TemporaryGrant

    # 等待被打断（取消/超时）：不允许，按取消/拒绝收尾
    if not outcome.success:
        if outcome.error_code == "cancelled":
            return _finish_record(
                record, outcome, status="cancelled",
                started=ask.started_mono, started_at_seq=record.started_at_seq,
                params_summary=record.params_summary,
            )
        denied = ToolCallOutcome(
            success=False, error_code="permission_denied_by_user",
            message=(
                "用户未确认路径访问授权，本次操作被拒绝："
                f"{permission_info.resolved_paths[0] if permission_info.resolved_paths else ''}"
            ),
        )
        return _finish_record(
            record, denied, status="denied",
            started=ask.started_mono, started_at_seq=record.started_at_seq,
            params_summary=record.params_summary,
        )

    # 读取回答（挂起注册表已清理，但 pending 对象仍被引用，selected 可读）
    selected = ask.pending.selected
    if PERMISSION_ALLOW_LABEL not in selected:
        denied = ToolCallOutcome(
            success=False, error_code="permission_denied_by_user",
            message=f"用户拒绝了本次路径访问授权：{'、'.join(permission_info.resolved_paths)}",
        )
        return _finish_record(
            record, denied, status="denied",
            started=ask.started_mono, started_at_seq=record.started_at_seq,
            params_summary=record.params_summary,
        )

    # 允许 → 临时授权（最小权限：仅授权被请求的路径本身，Invariant 5）
    assert ctx.permission is not None
    for path in permission_info.resolved_paths:
        ctx.permission.grants.append(TemporaryGrant(path=path))

    # 重执行原工具调用（权限已定，直接分发；重执行异常按结构化失败兜底）
    started = time.monotonic()
    try:
        if permission_info.tool_ref == "shell":
            outcome = _run_builtin(
                "shell", permission_info.arguments, session,
                shell_cwd=_resolve_shell_cwd(permission_info.arguments, ctx.permission),
            )
        else:
            outcome = _run_builtin(permission_info.tool_ref, permission_info.arguments, session)
    except Exception as exc:  # noqa: BLE001 — 与 run_tool 同哲学：结构化失败
        logger.exception("[runtime] 权限放行后工具重执行异常 %s", permission_info.tool_ref)
        outcome = ToolCallOutcome(
            success=False, error_code="execution_error", message=f"工具执行出错：{exc}",
        )
    if outcome.success:
        status = "success"
    elif outcome.error_code == "cancelled":
        status = "cancelled"
    else:
        status = "error"
    return _finish_record(
        record, outcome, status=status,
        started=started, started_at_seq=record.started_at_seq,
        params_summary=record.params_summary,
    )


# ---- 013：ask_user 专用（挂起等待语义，specs/013 research R1/R2）----


def _begin_ask_user(
    arguments: dict[str, Any], call_id: str, ctx: ToolContext,
) -> tuple[ToolCallOutcome, "AskPendingInfo | None"]:
    """ask_user 前半段：无人值守判定 + 参数校验 + 注册挂起。

    返回 (失败 outcome, None) 或 (占位 outcome, AskPendingInfo)；等待在后半段。
    """
    from app.services.agent_runtime import ask_user as ask_registry
    from app.services.tool_registry import AskUserParams

    # 无人值守（评测直调）：reply_message_id 为空 = 无聊天界面在场（research R2）
    if getattr(ctx.run_request, "reply_message_id", None) is None:
        return ToolCallOutcome(
            success=False,
            error_code="ask_user_unavailable",
            message="当前为自动运行（无聊天界面），没有用户可以回答；请基于已有信息继续或调整方案",
        ), None

    try:
        params = AskUserParams(**arguments)
    except Exception as exc:  # noqa: BLE001 — pydantic 校验失败统一 invalid_params
        first = getattr(exc, "errors", lambda: [])()
        detail = str(first[0].get("msg", "参数不合法")) if first else "参数不合法"
        return ToolCallOutcome(
            success=False, error_code="invalid_params",
            message=f"参数不符合要求：{detail.removeprefix('Value error, ')}",
        ), None

    options = list(params.options or [])
    pending = ask_registry.register(call_id)
    info = AskPendingInfo(
        pending=pending,
        question=params.question.strip(),
        options=options,
        multi_select=bool(params.multi_select) and bool(options),
        started_mono=time.monotonic(),
    )
    return ToolCallOutcome(success=True), info


async def await_ask_user(
    ask_info: "AskPendingInfo", call_id: str, ctx: ToolContext,
) -> ToolCallOutcome:
    """ask_user 后半段：等待回答 / 取消 / 超时（三路竞争，契约 §4）。

    永不抛异常；finally 清理注册表（运行结束零残留）。
    """
    import asyncio as _asyncio

    from app.core.config import settings as _settings
    from app.services.agent_runtime import ask_user as ask_registry

    try:
        wait_task = _asyncio.create_task(ask_info.pending.answered.wait())
        cancel_task = _asyncio.create_task(ctx.cancel.wait())
        timeout = float(_settings.ask_user_timeout_seconds)
        try:
            await _asyncio.wait(
                {wait_task, cancel_task}, timeout=timeout,
                return_when=_asyncio.FIRST_COMPLETED,
            )
        finally:
            wait_task.cancel()
            cancel_task.cancel()

        if ctx.cancel.is_set():
            return ToolCallOutcome(
                success=False, error_code="cancelled",
                message="运行已取消，询问未获得回答",
            )
        if not ask_info.pending.answered.is_set():
            # 超时（wait 超时返回且 cancel 未置位）
            return ToolCallOutcome(
                success=False, error_code="ask_user_timeout",
                message=(
                    f"用户未在 {int(timeout)} 秒内回答本次询问。"
                    "请基于已有信息继续，或调整方案后再询问"
                ),
            )
        answer_text = ask_registry.format_answer_text(
            ask_info.pending.selected, ask_info.pending.text,
        )
        return ToolCallOutcome(
            success=True, result_for_model=answer_text,
            summary=_summary(answer_text),
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — 与 run_tool 同哲学：结构化失败
        logger.exception("[runtime] ask_user 等待异常 call_id=%s", call_id)
        return ToolCallOutcome(
            success=False, error_code="execution_error",
            message=f"询问等待出错：{exc}"[:300],
        )
    finally:
        ask_registry.remove(call_id)


def finish_ask_user_record(
    record: ToolCallRecord, outcome: ToolCallOutcome,
) -> ToolCallRecord:
    """ask_user 等待结束后补全记录：状态映射同 run_tool（时长自 ask 起点续算）。"""
    ask = record.ask
    assert ask is not None
    if outcome.success:
        status = "success"
    elif outcome.error_code == "cancelled":
        status = "cancelled"
    elif outcome.error_code == "invalid_params":
        status = "denied"
    else:
        status = "error"
    return _finish_record(
        record, outcome, status=status,
        started=ask.started_mono,
        started_at_seq=record.started_at_seq,
        params_summary=record.params_summary,
    )


async def _run_mcp(
    entry: ToolCatalogEntry, arguments: dict[str, Any], ctx: ToolContext, session: Session,
) -> ToolCallOutcome:
    """MCP 工具：jsonschema 校验参数 → 会话 call_tool → 结果文本化。"""
    import jsonschema

    server_id = entry.server_id
    mcp_session = ctx.mcp_sessions.get(server_id) if server_id is not None else None
    if mcp_session is None:
        # 目录有但连接不可用（启动失败/断连）：明确 mcp_error（Edge Cases）
        return ToolCallOutcome(
            success=False, error_code=MCP_ERROR,
            message=f"MCP 工具不可用：{entry.exposed_name} 所属 Server 未连接，请稍后重试",
        )

    # MCP Server 启用状态复核（绑定关系在目录构建时已确认；此处复核 enabled，
    # 目录构建后运行中停用 → denied，FR-023）
    server = session.get(McpServerEntry, server_id)
    if server is None or not server.enabled:
        return ToolCallOutcome(
            success=False, error_code="tool_disabled",
            message=f"MCP Server 已停用：工具 {entry.exposed_name} 不可调用",
        )

    try:
        jsonschema.validate(instance=arguments, schema=entry.parameters)
    except jsonschema.ValidationError as exc:
        return ToolCallOutcome(
            success=False, error_code="invalid_params",
            message=f"参数不符合要求：{exc.message}",
        )
    try:
        result = await mcp_session.call_tool(entry.ref, arguments=arguments)
    except Exception as exc:  # noqa: BLE001 — 调用失败结构化交还（Edge Cases）
        logger.warning("[runtime] MCP 工具 %s 调用失败：%s", entry.exposed_name, exc)
        return ToolCallOutcome(
            success=False, error_code=MCP_ERROR,
            message=f"MCP 工具调用失败：{type(exc).__name__}: {exc}"[:500],
        )
    if getattr(result, "isError", False):
        texts = _content_texts(result.content)
        return ToolCallOutcome(
            success=False, error_code=MCP_ERROR,
            message="MCP 工具返回错误：" + ("".join(texts) or "未知错误")[:500],
        )
    texts = _content_texts(result.content)
    output = "".join(texts)
    return ToolCallOutcome(success=True, result_for_model=output, summary=_summary(output))


def _content_texts(content: Any) -> list[str]:
    """MCP CallToolResult.content → 文本片段列表（只取 TextContent）。"""
    texts: list[str] = []
    for item in content or []:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            texts.append(text)
    return texts

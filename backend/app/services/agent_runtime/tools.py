"""运行内工具目录、命名映射与统一执行入口（specs/009-agent-runtime 契约 §4）。

命名规则：内置=注册表原名；MCP=mcp__{消毒Server名}__{原名}（冲突追加 _2/_3…）；
load_skill 为保留名（仅存在可用 Skill 时提供）。执行入口永不抛异常，
失败也是结构化返回交还模型。
"""

import asyncio
import json
import logging
import re
import time
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AgentBinding, McpServerEntry, SkillEntry, ToolEntry
from app.schemas.mcp import McpToolInfo
from app.services import mcp_client, skill_files

if TYPE_CHECKING:
    from app.services.agent_runtime import RunLimits, RunRequest
    from app.services.agent_runtime.events import RunEventEmitter

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
    status: str = ""  # success | error | denied | cancelled
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
        skill_ids = {sid for sid in skill_ids if f"mcp__placeholder load" }

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


async def run_tool(
    exposed_name: str,
    raw_arguments: "dict[str, Any] | str",
    ctx: ToolContext,
    session: Session,
) -> ToolCallRecord:
    """统一执行入口：目录查名 → 取消检查 → 分发执行 → 记录（FR-022/023）。

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

        # ② 分发执行（各类型内部再做 DB 复核与参数校验）
        if entry.tool_type == TOOL_TYPE_SKILL:
            outcome = load_skill(session, ctx, str(arguments.get("skill_id", "")))
        elif entry.tool_type == TOOL_TYPE_BUILTIN:
            outcome = _run_builtin(entry.ref, arguments, session)
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


def _run_builtin(name: str, arguments: dict[str, Any], session: Session) -> ToolCallOutcome:
    """内置工具：委托 tool_executor.execute（启停/参数/危险命令校验都在其中）。"""
    from app.services.tool_executor import execute

    result = execute(name, arguments, session)
    if result.success:
        return ToolCallOutcome(
            success=True, result_for_model=result.output or "",
            summary=_summary(result.output or ""),
        )
    return ToolCallOutcome(
        success=False, error_code=result.error_code or "execution_error",
        message=result.message, summary=_summary(result.message or ""),
    )


async def _run_mcp(
    entry: ToolCatalogEntry, arguments: dict[str, Any], ctx: ToolContext, session: Session,
) -> ToolCallOutcome:
    """MCP 工具：jsonschema 校验参数 → 会话 call_tool → 结果文本化。"""
    import jsonschema

    from app.services.agent_runtime.skills import _failure as _skill_failure
    from app.services.agent_runtime.skills import (
        SKILL_DISABLED,
        SKILL_NOT_BOUND,
    )

    server_id = entry.server_id
    mcp_session = ctx.mcp_sessions.get(server_id) if server_id is not None else None
    if mcp_session is None:
        # 目录有但连接不可用（启动失败/断连）：明确 mcp_error（Edge Cases）
        return ToolCallOutcome(
            success=False, error_code=MCP_ERROR,
            message=f"MCP 工具不可用：{entry.exposed_name} 所属 Server 未连接，请稍后重试",
        )

    # DB 复核启用状态（执行前再次校验，FR-023）
    from app.models import McpServerEntry as _Entry


    # MCP Server 启用状态复核（绑定关系在目录构建时已确认；此处复核 enabled，
    # 目录构建后运行中停用 → denied，FR-023）
    server = session.get(McpServerEntry, server_id)
    if server is None or not server.enabled:
        from app.services.agent_runtime.skills import _failure as _skill_failure
        from app.services.agent_runtime.skills import SKILL_DISABLED

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

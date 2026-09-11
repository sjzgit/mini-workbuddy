"""MCP 管理业务逻辑：CRUD、掩码、三态合并、启停、测试编排与快照落库。

数据层主定义：specs/004-skills-mcp-management/data-model.md
契约主定义：specs/004-skills-mcp-management/contracts/mcp-api.md
敏感值（env/headers）：JSON 序列化 → secret_vault 加密，本模块任何返回不含明文（FR-023，research R5）。
"""

import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import secret_vault
from app.models import McpServerEntry
from app.schemas.mcp import (
    McpServerDetail,
    McpServerItem,
    McpServerUpsertRequest,
    McpTestResult,
    McpToolInfo,
    mask_value,
)
from app.services import mcp_client
from app.services.mcp_client import TransportConfig

# 快照状态（data-model.md：NULL=未测试 / success / failed / config_changed）
STATUS_UNTESTED = None
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CONFIG_CHANGED = "config_changed"

_CONFIG_CHANGED_MESSAGE = "配置已变更，待重新测试"


class McpNotFoundError(LookupError):
    """Server 不存在（路由层转 404）。"""


class McpNameConflictError(ValueError):
    """同名 Server（路由层转 400）。"""


class McpBusyError(RuntimeError):
    """该 Server 测试进行中（重复测试/编辑/删除被拒，路由层转 400，FR-030）。"""


# per-Server 测试互斥锁（research R6：常驻不清理，数量=曾测试的 Server 数，进程重启自然清零）
_test_locks: dict[int, asyncio.Lock] = {}


def _lock_for(server_id: int) -> asyncio.Lock:
    if server_id not in _test_locks:
        _test_locks[server_id] = asyncio.Lock()
    return _test_locks[server_id]


def is_testing(server_id: int) -> bool:
    """该 Server 是否正在测试（编辑/删除入口的前置检查）。"""
    return _test_locks[server_id].locked() if server_id in _test_locks else False


def _load_secrets(session: Session, entry: McpServerEntry) -> tuple[dict[str, str], dict[str, str]]:
    """解密 env 与 headers（仅供进程内使用：连接构造与值比较；绝不进响应/日志）。"""
    env: dict[str, str] = {}
    headers: dict[str, str] = {}
    env_raw = secret_vault.load_secret(session, entry.env_secret_ref)
    if env_raw:
        env = dict(json.loads(env_raw))
    headers_raw = secret_vault.load_secret(session, entry.headers_secret_ref)
    if headers_raw:
        headers = dict(json.loads(headers_raw))
    return env, headers


def _to_item(entry: McpServerEntry) -> McpServerItem:
    return McpServerItem(
        id=entry.id,
        name=entry.name,
        description=entry.description,
        server_type=entry.server_type,  # type: ignore[arg-type]
        enabled=entry.enabled,
        last_test_status=entry.last_test_status,  # type: ignore[arg-type]
        last_test_message=entry.last_test_message,
        last_test_tool_count=entry.last_test_tool_count,
        last_test_at=entry.last_test_at.isoformat() if entry.last_test_at else None,
        updated_at=entry.updated_at.isoformat(),
    )


def _to_detail(session: Session, entry: McpServerEntry) -> McpServerDetail:
    env, headers = _load_secrets(session, entry)
    return McpServerDetail(
        **_to_item(entry).model_dump(),
        command=entry.command,
        command_args=list(entry.command_args) if entry.command_args is not None else None,
        env_masked={key: mask_value() for key in env} if env else None,
        url=entry.url,
        headers_masked={key: mask_value() for key in headers} if headers else None,
        tools=mcp_client.loads_tools(entry.tools_json),
    )


def list_servers(session: Session) -> list[McpServerItem]:
    """列表（FR-015）：updated_at 倒序。"""
    entries = session.scalars(
        select(McpServerEntry).order_by(McpServerEntry.updated_at.desc(), McpServerEntry.id.desc()),
    ).all()
    return [_to_item(entry) for entry in entries]


def get_server(session: Session, server_id: int) -> McpServerDetail:
    entry = session.get(McpServerEntry, server_id)
    if entry is None:
        raise McpNotFoundError(f"MCP Server {server_id} 不存在")
    return _to_detail(session, entry)


def create_server(session: Session, payload: McpServerUpsertRequest) -> McpServerDetail:
    """新增：敏感值加密入库；创建即启用、无测试结果（契约 §3.3）。"""
    if session.scalar(select(McpServerEntry).where(McpServerEntry.name == payload.name)):
        raise McpNameConflictError(payload.name)
    entry = McpServerEntry(
        name=payload.name,
        description=payload.description,
        server_type=payload.server_type,
        command=payload.command,
        command_args=list(payload.command_args) if payload.command_args is not None else None,
        url=payload.url,
        enabled=True,
    )
    session.add(entry)
    session.flush()  # 取得 id，再挂密文

    env = {key: value for key, value in (payload.env or {}).items() if value is not None}
    headers = {key: value for key, value in (payload.headers or {}).items() if value is not None}
    entry.env_secret_ref = secret_vault.store_secret(
        session, None, json.dumps(env, ensure_ascii=False) if env else "",
    )
    entry.headers_secret_ref = secret_vault.store_secret(
        session, None, json.dumps(headers, ensure_ascii=False) if headers else "",
    )
    session.commit()
    return _to_detail(session, entry)


def _merge_overrides(
    session: Session, secret_ref: int | None, overrides: dict[str, str | None] | None,
) -> int | None:
    """三态合并（契约 §2）：None 保留原值、字符串替换/新增、键缺席删除；返回新 secret_ref。"""
    if overrides is None:
        return secret_ref  # 表单未提供该部分（如 http 表单不含 env）：整体保留
    current: dict[str, str] = {}
    raw = secret_vault.load_secret(session, secret_ref)
    if raw:
        current = dict(json.loads(raw))
    # 以 overrides 为准重建：字符串 → 新值；None → 从原值带过来；缺席 → 丢弃
    kept: dict[str, str] = {}
    for key, value in overrides.items():
        if value is None:
            if key in current:
                kept[key] = current[key]
        else:
            kept[key] = value
    if kept:
        return secret_vault.store_secret(session, secret_ref, json.dumps(kept, ensure_ascii=False))
    secret_vault.delete_secret(session, secret_ref)  # 全部键被删除：清密文
    return None


def _config_fingerprint(
    command: str | None,
    command_args: list[str] | None,
    env: dict[str, str],
    url: str | None,
    headers: dict[str, str],
) -> tuple:
    """连接相关五项的值指纹（config_changed 判定用，research R6）。"""
    return (
        command or "",
        tuple(command_args or []),
        tuple(sorted(env.items())),
        url or "",
        tuple(sorted(headers.items())),
    )


def update_server(
    session: Session, server_id: int, payload: McpServerUpsertRequest,
) -> McpServerDetail:
    """编辑：三态合并敏感值；连接五项实际变化且有旧结果 → config_changed（FR-034）。"""
    entry = session.get(McpServerEntry, server_id)
    if entry is None:
        raise McpNotFoundError(f"MCP Server {server_id} 不存在")
    if is_testing(server_id):
        raise McpBusyError("正在测试中，请稍后再试")
    if payload.name != entry.name and session.scalar(
        select(McpServerEntry).where(McpServerEntry.name == payload.name),
    ):
        raise McpNameConflictError(payload.name)

    old_env, old_headers = _load_secrets(session, entry)
    old_fingerprint = _config_fingerprint(
        entry.command, entry.command_args, old_env, entry.url, old_headers,
    )

    entry.name = payload.name
    entry.description = payload.description
    entry.server_type = payload.server_type
    entry.command = payload.command
    entry.command_args = list(payload.command_args) if payload.command_args is not None else None
    entry.url = payload.url

    env_changed = payload.env is not None
    headers_changed = payload.headers is not None
    entry.env_secret_ref = _merge_overrides(session, entry.env_secret_ref, payload.env)
    entry.headers_secret_ref = _merge_overrides(session, entry.headers_secret_ref, payload.headers)

    new_env, new_headers = _load_secrets(session, entry)
    new_fingerprint = _config_fingerprint(
        entry.command, entry.command_args, new_env, entry.url, new_headers,
    )
    if (
        new_fingerprint != old_fingerprint
        and entry.last_test_status is not None
        and entry.last_test_status != STATUS_CONFIG_CHANGED
    ):
        entry.last_test_status = STATUS_CONFIG_CHANGED
        entry.last_test_message = _CONFIG_CHANGED_MESSAGE
        # 保留旧 tool_count / tools_json：仍是"最近一次成功测试"的事实（research R6）

    session.add(entry)
    session.commit()
    return _to_detail(session, entry)


def delete_server(session: Session, server_id: int) -> None:
    """删除：行 + 两份密文同删；测试进行中拒绝（Edge Case）。"""
    entry = session.get(McpServerEntry, server_id)
    if entry is None:
        raise McpNotFoundError(f"MCP Server {server_id} 不存在")
    if is_testing(server_id):
        raise McpBusyError("正在测试中，请稍后再试")
    secret_vault.delete_secret(session, entry.env_secret_ref)
    secret_vault.delete_secret(session, entry.headers_secret_ref)
    session.delete(entry)
    session.commit()


def set_enabled(session: Session, server_id: int, enabled: bool) -> McpServerItem:
    """启停（FR-032）：不影响测试结果，不触发 config_changed。"""
    entry = session.get(McpServerEntry, server_id)
    if entry is None:
        raise McpNotFoundError(f"MCP Server {server_id} 不存在")
    entry.enabled = enabled
    session.add(entry)
    session.commit()
    return _to_item(entry)


async def test_server(session: Session, server_id: int) -> McpTestResult:
    """测试连接（US6/US7）：互斥锁 → 解密配置 → 连接发现 → 快照落库（FR-025~034）。

    仅发现工具不执行（FR-026）；成败超时均清理连接与子进程（mcp_client 保证，FR-031）。
    """
    entry = session.get(McpServerEntry, server_id)
    if entry is None:
        raise McpNotFoundError(f"MCP Server {server_id} 不存在")
    lock = _lock_for(server_id)
    if lock.locked():
        raise McpBusyError("该 Server 正在测试中")

    env, headers = _load_secrets(session, entry)
    config = TransportConfig(
        server_type=entry.server_type,
        command=entry.command,
        command_args=list(entry.command_args or []) if entry.command_args else [],
        env=env,
        url=entry.url,
        headers=headers,
    )

    tools: list[McpToolInfo] = []
    failure: mcp_client.McpTestFailure | None = None
    async with lock:
        try:
            tools = await mcp_client.connect_and_list(config)
        except mcp_client.McpTestFailure as exc:
            failure = exc

    # 快照落库（成功与失败都更新；不改 enabled，FR-033）
    entry = session.get(McpServerEntry, server_id)
    if entry is None:  # 测试期间被删除
        raise McpNotFoundError(f"MCP Server {server_id} 不存在")
    entry.last_test_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    if failure is None:
        entry.last_test_status = STATUS_SUCCESS
        entry.last_test_tool_count = len(tools)
        entry.last_test_message = (
            "连接成功，未发现工具" if not tools else f"连接成功，发现 {len(tools)} 个工具"
        )
        entry.tools_json = mcp_client.dumps_tools(tools)
    else:
        entry.last_test_status = STATUS_FAILED
        entry.last_test_tool_count = None
        entry.last_test_message = failure.message
    session.add(entry)
    session.commit()

    return McpTestResult(
        status=STATUS_SUCCESS if failure is None else STATUS_FAILED,
        category=None if failure is None else failure.category,  # type: ignore[arg-type]
        message=entry.last_test_message or "",
        tool_count=entry.last_test_tool_count,
        tools=tools,
        item=_to_item(entry),
    )

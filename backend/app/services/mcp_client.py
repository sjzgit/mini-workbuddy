"""MCP SDK 客户端封装：连接 → 协议初始化 → 工具发现 → 清理（async、无 DB 依赖）。

契约主定义：specs/004-skills-mcp-management/contracts/mcp-api.md §5（六分类与脱敏）
设计依据：research R3（官方 SDK，命令+参数数组直传进程，无 Shell 拼接）、R4（异常类型判别分类）。
"""

import asyncio
import json
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.exceptions import MCPError

from app.core.config import settings
from app.schemas.mcp import McpToolInfo, parse_input_schema

# 失败分类（枚举主定义：契约 mcp-api.md §5）
Category = str  # TestCategory Literal 的运行时形态

CATEGORY_MESSAGE = {
    "command_not_found": "启动命令不存在：请确认命令已安装且可在本机直接运行",
    "process_failed": "程序启动失败或提前退出：请核对启动命令与参数是否完整",
    "timeout": "连接或读取工具超时（{timeout} 秒）：Server 启动缓慢或无响应",
    "protocol_incompatible": "协议版本或响应格式不兼容：该 Server 与本系统支持的 MCP 协议不匹配",
    "server_error": "Server 返回错误：{detail}",
    "connection_failed": "连接失败：地址不可达或端口错误，请核对 url 与网络可达性",
    "unknown": "未知错误：暂时无法确定原因。诊断信息：{detail}",
}

_DIAG_MAX_CHARS = 500


@dataclass
class TransportConfig:
    """连接所需的最小配置（从 Server 配置解密后构造，绝不进日志/诊断）。"""

    server_type: str  # stdio | http
    command: str | None = None
    command_args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None


class McpTestFailure(Exception):
    """测试失败（携带分类与人话信息），由调用方落库为失败快照。"""

    def __init__(self, category: Category, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


def sanitize(text: str, secrets: list[str]) -> str:
    """脱敏纯函数（FR-023，契约 §6）：本 Server 配置中的敏感值（长度 ≥ 4）全量替换为 ******。"""
    result = text
    for secret in secrets:
        if len(secret) >= 4:
            result = result.replace(secret, "******")
    return result[:_DIAG_MAX_CHARS]


def _classify(exc: Exception) -> Category:
    """异常类型 → 失败分类（research R4：按类型判别，不靠字符串猜测）。

    ExceptionGroup（anyio TaskGroup 包装）取子异常中第一个可分类者。
    """
    if isinstance(exc, BaseExceptionGroup):
        for sub in _flatten_exceptions(exc):
            category = _classify(sub)
            if category != "unknown":
                return category
        return "unknown"
    # 顺序敏感：先具体后一般
    if isinstance(exc, FileNotFoundError):
        return "command_not_found"
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    # 流关闭/EOF 是"进程死亡"的强信号，优先于协议类错误（进程退出常被包装成读失败）
    if isinstance(exc, (EOFError, BrokenPipeError)):
        return "process_failed"
    try:  # anyio 流关闭（SDK 内部依赖），进程提前退出的典型形态
        from anyio import BrokenResourceError, ClosedResourceError

        if isinstance(exc, (ClosedResourceError, BrokenResourceError)):
            return "process_failed"
    except ImportError:  # pragma: no cover - mcp 必带 anyio
        pass
    if isinstance(exc, MCPError):
        return "protocol_incompatible"
    # OSError 家族：连接拒绝/网络不可达 → connection_failed；其余（进程孵化失败等）
    # 若发生在 stdio 启动语境，由上层 FileNotFoundError 先行分流，这里按连接失败兜底
    if isinstance(exc, OSError):
        return "connection_failed"
    return "unknown"


def _failure_from(category: Category, exc: Exception, secrets: list[str]) -> McpTestFailure:
    detail = sanitize(f"{type(exc).__name__}: {exc}", secrets)
    if category == "server_error":
        message = CATEGORY_MESSAGE["server_error"].format(detail=detail)
    elif category == "timeout":
        message = CATEGORY_MESSAGE["timeout"].format(timeout=settings.mcp_test_timeout_seconds)
    elif category == "unknown":
        message = CATEGORY_MESSAGE["unknown"].format(detail=detail)
    else:
        message = CATEGORY_MESSAGE[category]
    return McpTestFailure(category=category, message=message)


async def connect_and_list(config: TransportConfig) -> list[McpToolInfo]:
    """连接 → initialize → list_tools → 清理；仅发现工具，绝不调用工具（FR-026）。

    任何失败抛 McpTestFailure（分类已定）；async with 退出保证连接与子进程清理（FR-031）。
    """
    try:
        return await asyncio.wait_for(_connect_and_list(config), settings.mcp_test_timeout_seconds)
    except McpTestFailure:
        raise
    except asyncio.TimeoutError as exc:
        raise McpTestFailure(
            category="timeout",
            message=CATEGORY_MESSAGE["timeout"].format(timeout=settings.mcp_test_timeout_seconds),
        ) from exc
    except Exception as exc:  # noqa: BLE001 - 统一分类兜底
        secrets = list((config.env or {}).values()) + list((config.headers or {}).values())
        raise _failure_from(_classify(exc), exc, secrets) from exc


def _flatten_exceptions(exc: BaseException) -> list[Exception]:
    """展开 ExceptionGroup（anyio TaskGroup 包装），取子异常参与分类。"""
    if isinstance(exc, BaseExceptionGroup):
        flattened: list[Exception] = []
        for sub in exc.exceptions:
            flattened.extend(_flatten_exceptions(sub))
        return flattened  # type: ignore[return-value]
    if isinstance(exc, Exception):
        return [exc]
    return []


async def _connect_and_list(config: TransportConfig) -> list[McpToolInfo]:
    """按传输形态建立会话并读取工具列表。"""
    async with AsyncExitStack() as stack:
        if config.server_type == "stdio":
            assert config.command is not None
            env_base = get_default_environment()
            env_base.update(config.env or {})
            params = StdioServerParameters(
                command=config.command,
                args=list(config.command_args or []),
                env=env_base,
            )
            read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
        else:
            assert config.url is not None
            # 自定义 Header 经预配置的 httpx 客户端注入（SDK 契约：headers 走 http_client）
            http_client = (
                create_mcp_http_client(headers=config.headers or None)
                if config.headers
                else None
            )
            streams = await stack.enter_async_context(
                streamable_http_client(config.url, http_client=http_client),
            )
            read_stream, write_stream = streams[0], streams[1]

        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        result = await session.list_tools()
        return [
            McpToolInfo(
                name=tool.name,
                description=tool.description or "",
                params=parse_input_schema(tool.input_schema),
            )
            for tool in result.tools
        ]


def tool_count_or_none(tools: list[McpToolInfo]) -> int:
    """工具数量（快照列）。"""
    return len(tools)


def dumps_tools(tools: list[McpToolInfo]) -> str:
    """工具快照序列化（tools_json 列）。"""
    return json.dumps(
        [tool.model_dump() for tool in tools], ensure_ascii=False, separators=(",", ":"),
    )


def loads_tools(raw: str | None) -> list[McpToolInfo]:
    """工具快照反序列化；损坏数据按空快照处理（不抛）。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [McpToolInfo.model_validate(item) for item in data]
    except (ValueError, TypeError):
        return []


def schema_to_params(schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    """暴露给测试的参数表解析（与 parse_input_schema 同源的调试入口）。"""
    return [param.model_dump() for param in parse_input_schema(schema)]

"""mcp_client 单元测试：脱敏、错误分类、schema 解析（tasks T033）。

不依赖真实进程；分类经注入异常验证。
"""

import asyncio
from pathlib import Path

import pytest
from anyio import BrokenResourceError, ClosedResourceError
from mcp.shared.exceptions import MCPError

from app.services import mcp_client
from app.services.mcp_client import TransportConfig, sanitize


def _client_mod(monkeypatch: pytest.MonkeyPatch):
    """重载模块级 _classify 所需依赖已直接 import——此夹具预留超时覆盖。"""
    monkeypatch.setattr("app.core.config.settings.mcp_test_timeout_seconds", 1)
    return mcp_client


# ---- sanitize（SC-005 的核心函数）----


def test_sanitize_replaces_long_secrets() -> None:
    text = "connect failed with token secret-value-1234 at host"
    result = sanitize(text, ["secret-value-1234"])
    assert "secret-value-1234" not in result
    assert "******" in result
    assert "connect failed with token" in result


def test_sanitize_keeps_short_values() -> None:
    """长度 < 4 的值不替换（如 "on"/"1"），避免全文变掩码。"""
    assert sanitize("flag is on", ["on"]) == "flag is on"


def test_sanitize_truncates_to_500() -> None:
    result = sanitize("x" * 2000, [])
    assert len(result) == 500


def test_sanitize_empty_secrets_noop() -> None:
    assert sanitize("plain", []) == "plain"


# ---- 错误分类（契约 mcp-api.md §5，research R4）----


def test_classify_file_not_found() -> None:
    assert mcp_client._classify(FileNotFoundError()) == "command_not_found"


def test_classify_timeout() -> None:
    assert mcp_client._classify(asyncio.TimeoutError()) == "timeout"


def test_classify_process_failed_via_anyio() -> None:
    assert mcp_client._classify(ClosedResourceError()) == "process_failed"
    assert mcp_client._classify(BrokenResourceError()) == "process_failed"
    assert mcp_client._classify(EOFError()) == "process_failed"


def test_classify_protocol_incompatible() -> None:
    error = MCPError(1, "version mismatch")
    assert mcp_client._classify(error) == "protocol_incompatible"


def test_classify_connection_failed() -> None:
    assert mcp_client._classify(ConnectionRefusedError()) == "connection_failed"


def test_classify_unknown_fallback() -> None:
    assert mcp_client._classify(ValueError("weird")) == "unknown"


def test_connect_and_list_timeout_maps(monkeypatch: pytest.MonkeyPatch) -> None:
    """总超时触发 → McpTestFailure(timeout)。"""
    monkeypatch.setattr("app.core.config.settings.mcp_test_timeout_seconds", 1)

    async def never_returns(_config: TransportConfig) -> list:
        await asyncio.sleep(10)
        return []

    monkeypatch.setattr(mcp_client, "_connect_and_list", never_returns)
    with pytest.raises(mcp_client.McpTestFailure) as exc_info:
        asyncio.run(mcp_client.connect_and_list(TransportConfig(server_type="stdio")))
    assert exc_info.value.category == "timeout"


def test_failure_message_not_leaking_secrets() -> None:
    """unknown 分类的诊断信息经脱敏（FR-029）。"""
    config = TransportConfig(server_type="stdio", env={"TOKEN": "super-secret-token"})
    try:
        asyncio.run(mcp_client.connect_and_list(config))
    except mcp_client.McpTestFailure as failure:
        if failure.category == "unknown":
            assert "super-secret-token" not in failure.message


# ---- inputSchema 解析（契约 §2 McpToolParam）----


def test_parse_input_schema_full() -> None:
    schema = {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名"},
            "days": {"type": "integer"},
            "options": {"type": "object"},
        },
        "required": ["city"],
    }
    params = {param["name"]: param for param in mcp_client.schema_to_params(schema)}
    assert params["city"]["type"] == "string"
    assert params["city"]["required"] is True
    assert params["city"]["description"] == "城市名"
    assert params["days"]["type"] == "integer"
    assert params["days"]["required"] is False
    assert params["options"]["type"] == "object"


def test_parse_input_schema_empty_or_invalid() -> None:
    assert mcp_client.schema_to_params(None) == []
    assert mcp_client.schema_to_params({"type": "string"}) == []
    assert mcp_client.schema_to_params({"type": "object"}) == []


# ---- 工具快照序列化 ----


def test_tools_json_roundtrip() -> None:
    from app.schemas.mcp import McpToolInfo, McpToolParam

    tools = [
        McpToolInfo(
            name="t1",
            description="描述",
            params=[McpToolParam(name="a", type="string", required=True, description="")],
        ),
    ]
    raw = mcp_client.dumps_tools(tools)
    loaded = mcp_client.loads_tools(raw)
    assert loaded == tools
    assert mcp_client.loads_tools(None) == []
    assert mcp_client.loads_tools("broken json") == []

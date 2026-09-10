"""统一执行入口测试（US3 五场景，FR-009~012）。

每个失败场景后"进程存活"以"无异常冒泡"体现——execute() 的返回值即证明。
"""

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.schemas.tool import ToolExecutionResult
from app.services import tool_executor
from app.services.tool_executor import ToolExecutionError


def _exec(
    name: str, params: dict[str, Any], session: Session,
) -> ToolExecutionResult:
    """便捷封装：任何输入都不应抛异常（FR-012 的断言载体）。"""
    return tool_executor.execute(name, params, session)


def test_success_current_time(tools_seeded: Session) -> None:
    result = _exec("current_time", {"timezone": "Asia/Shanghai"}, tools_seeded)
    assert result.success is True
    assert result.error_code is None
    assert result.output  # 时间字符串存在
    assert result.extra == {"timezone": "Asia/Shanghai"}


def test_tool_not_found(tools_seeded: Session) -> None:
    result = _exec("no_such_tool", {}, tools_seeded)
    assert result.success is False
    assert result.error_code == "tool_not_found"
    assert "no_such_tool" in result.message


def test_tool_disabled(tools_seeded: Session) -> None:
    from sqlalchemy import update

    from app.models import ToolEntry

    tools_seeded.execute(
        update(ToolEntry).where(ToolEntry.name == "current_time").values(enabled=False),
    )
    tools_seeded.commit()

    result = _exec("current_time", {}, tools_seeded)
    assert result.success is False
    assert result.error_code == "tool_disabled"
    assert "当前时间" in result.message  # 提示含显示名，便于使用者定位


def test_unseeded_row_is_not_found(tools_seeded: Session) -> None:
    """DB 行被清空 → 元数据仍在注册表，但执行入口按未注册处理（research R6）。"""
    from sqlalchemy import delete

    from app.models import ToolEntry

    tools_seeded.execute(delete(ToolEntry).where(ToolEntry.name == "shell"))
    tools_seeded.commit()

    result = _exec("shell", {"command": "dir"}, tools_seeded)
    assert result.success is False
    assert result.error_code == "tool_not_found"


def test_invalid_params_missing_field(tools_seeded: Session) -> None:
    result = _exec("file_read_write", {"action": "read"}, tools_seeded)
    assert result.success is False
    assert result.error_code == "invalid_params"
    assert "path" in result.message  # 指明缺失字段


def test_invalid_params_bad_enum(tools_seeded: Session) -> None:
    result = _exec("file_read_write", {"action": "append", "path": "a.txt"}, tools_seeded)
    assert result.success is False
    assert result.error_code == "invalid_params"


def test_invalid_params_command_too_long(tools_seeded: Session) -> None:
    result = _exec("shell", {"command": "x" * 10001}, tools_seeded)
    assert result.success is False
    assert result.error_code == "invalid_params"


def test_invalid_params_extra_field_rejected(tools_seeded: Session) -> None:
    result = _exec("current_time", {"timezone": "Etc/UTC", "extra": 1}, tools_seeded)
    assert result.success is False
    assert result.error_code == "invalid_params"


def test_execution_error_unexpected_exception(
    tools_seeded: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非 ToolExecutionError 的意外异常 → 兜底 execution_error，零崩溃（FR-012）。"""

    def _explode(_params: object) -> None:
        raise RuntimeError("内部炸了")

    monkeypatch.setattr("app.services.time_tool.run", _explode)
    result = _exec("current_time", {}, tools_seeded)
    assert result.success is False
    assert result.error_code == "execution_error"
    # 兜底为固定文案：不包含异常自身的细节（如 raise 的消息内容）
    assert result.message == "工具执行出错：发生未预期的内部错误，请检查输入后重试"


def test_tool_execution_error_passes_through(
    tools_seeded: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """工具实现抛 ToolExecutionError → code/message/extra 原样包装。"""

    def _rejected(_params: object) -> None:
        raise ToolExecutionError(
            code="unknown_timezone",
            message="无法识别时区",
            extra={"timezone": "CST"},
        )

    monkeypatch.setattr("app.services.time_tool.run", _rejected)
    result = _exec("current_time", {"timezone": "CST"}, tools_seeded)
    assert result.success is False
    assert result.error_code == "unknown_timezone"
    assert result.extra == {"timezone": "CST"}

"""current_time 工具测试（US5 验收 1–3 / SC-005，FR-013/014）。"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.services import tool_executor, time_tool
from app.services.tool_executor import ToolExecutionError
from app.services.tool_registry import CurrentTimeParams


def test_specified_timezone_shanghai(tools_seeded: Session) -> None:
    result = tool_executor.execute(
        "current_time", {"timezone": "Asia/Shanghai"}, tools_seeded,
    )
    assert result.success is True
    assert result.extra is not None
    assert result.extra["timezone"] == "Asia/Shanghai"
    # 输出是与 zoneinfo 计算同分钟的北京时间（容忍秒级执行耗时）
    expected = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    assert result.output is not None
    assert result.output.startswith(expected[:15])  # 精确到分钟


def test_specified_timezone_utc(tools_seeded: Session) -> None:
    result = tool_executor.execute(
        "current_time", {"timezone": "Etc/UTC"}, tools_seeded,
    )
    assert result.success is True
    assert result.extra == {"timezone": "Etc/UTC"}


def test_default_timezone_fallback(tools_seeded: Session) -> None:
    """未指定时区 → 系统默认时区（Asia/Shanghai），extra 仍注明。"""
    result = tool_executor.execute("current_time", {}, tools_seeded)
    assert result.success is True
    assert result.extra == {"timezone": "Asia/Shanghai"}


def test_cst_abbreviation_rejected() -> None:
    """CST 等模糊缩写不是合法 IANA 名称 → unknown_timezone（FR-014）。"""
    with pytest.raises(ToolExecutionError) as exc_info:
        time_tool.run(CurrentTimeParams(timezone="CST"))
    assert exc_info.value.code == "unknown_timezone"
    assert "IANA" in exc_info.value.message
    assert "Asia/Shanghai" in exc_info.value.message  # 文案含示例


def test_typo_timezone_rejected() -> None:
    with pytest.raises(ToolExecutionError) as exc_info:
        time_tool.run(CurrentTimeParams(timezone="Asia/Shangha"))
    assert exc_info.value.code == "unknown_timezone"


def test_cst_via_executor_is_structured(tools_seeded: Session) -> None:
    """经统一入口调用 → 结构化失败而非异常（US5 场景 3）。"""
    result = tool_executor.execute("current_time", {"timezone": "CST"}, tools_seeded)
    assert result.success is False
    assert result.error_code == "unknown_timezone"
    assert "IANA" in result.message

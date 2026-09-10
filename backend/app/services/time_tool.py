"""current_time 工具实现（FR-013/014，research R7）。

标准库 zoneinfo 按 IANA 名称严格解析：CST 等缩写与拼写错误天然被拒。
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings
from app.services.tool_executor import ToolExecutionError, ToolRunOutcome
from app.services.tool_registry import CurrentTimeParams


def run(params: CurrentTimeParams) -> ToolRunOutcome:
    """按指定时区（或系统默认时区）返回当前日期和时间。"""
    timezone_name = params.timezone if params.timezone else settings.default_timezone
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError, OSError) as exc:
        raise ToolExecutionError(
            code="unknown_timezone",
            message=(
                f'无法识别时区"{timezone_name}"。请使用 IANA 时区名称，'
                "如 Asia/Shanghai、America/New_York、Etc/UTC，避免 CST 等缩写"
            ),
        ) from exc
    now = datetime.now(zone)
    extra: dict[str, Any] = {"timezone": timezone_name}
    return ToolRunOutcome(
        success=True,
        output=now.strftime("%Y-%m-%d %H:%M:%S"),
        extra=extra,
        message=f"当前时间（{timezone_name}）",
    )

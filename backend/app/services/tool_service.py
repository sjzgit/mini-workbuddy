"""工具管理业务逻辑：列表 / 详情 / 启停 / 幂等播种。

数据层主定义：specs/003-tool-management/data-model.md
职责划分（research R1）：元数据查注册表，启停状态查 tools 表，两侧以 name 对齐。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ToolEntry
from app.schemas.tool import ToolDetail, ToolItem
from app.services import tool_registry


class ToolNotFoundError(LookupError):
    """工具不存在（路由层转 404）。"""


def _to_item(entry: ToolEntry) -> ToolItem:
    """DB 行 ⨝ 注册表元数据 → 列表项（注册表无此键的行不在此处理，见 list_tools）。"""
    definition = tool_registry.get_definition(entry.name)
    assert definition is not None  # 列表/详情路径已过滤
    return ToolItem(
        name=entry.name,
        display_name=definition.display_name,
        purpose=definition.purpose,
        params_summary=definition.params_summary,
        enabled=entry.enabled,
        is_builtin=definition.is_builtin,
        updated_at=entry.updated_at.isoformat(),
    )


def list_tools(session: Session) -> list[ToolItem]:
    """列表：按 name 字母序；注册表查无此键的行跳过（版本漂移兜底）。"""
    entries = session.scalars(select(ToolEntry).order_by(ToolEntry.name)).all()
    return [
        _to_item(entry)
        for entry in entries
        if tool_registry.is_registered(entry.name)
    ]


def get_tool(session: Session, name: str) -> ToolDetail:
    """详情：参数表 + 三节说明完整返回。"""
    if not tool_registry.is_registered(name):
        raise ToolNotFoundError(f"工具 {name} 不存在")
    entry = session.scalar(select(ToolEntry).where(ToolEntry.name == name))
    if entry is None:
        # 元数据存在但未播种（如数据被清空后仅跑了部分恢复）——对使用者等同不存在
        raise ToolNotFoundError(f"工具 {name} 不存在")
    definition = tool_registry.get_definition(name)
    assert definition is not None
    return ToolDetail(
        **_to_item(entry).model_dump(),
        params=definition.params,
        usage_scenarios=definition.usage_scenarios,
        input_requirements=definition.input_requirements,
        restrictions=definition.restrictions,
    )


def set_enabled(session: Session, name: str, enabled: bool) -> ToolItem:
    """启停：更新 enabled 并刷新 updated_at，返回完整列表项（FR-005）。"""
    if not tool_registry.is_registered(name):
        raise ToolNotFoundError(f"工具 {name} 不存在")
    entry = session.scalar(select(ToolEntry).where(ToolEntry.name == name))
    if entry is None:
        raise ToolNotFoundError(f"工具 {name} 不存在")
    entry.enabled = enabled
    session.add(entry)
    session.commit()
    return _to_item(entry)


def get_enabled(session: Session, name: str) -> bool | None:
    """查询启停状态；无行返回 None（执行入口视为未注册，research R6）。"""
    entry = session.scalar(select(ToolEntry).where(ToolEntry.name == name))
    return None if entry is None else entry.enabled


def ensure_seeded(session: Session) -> None:
    """幂等播种：补注册表中尚缺的行，不覆盖已有启停状态（research R1）。

    供测试夹具与运维恢复使用，正常运行不自动调用。
    """
    existing = set(session.scalars(select(ToolEntry.name)).all())
    for name in tool_registry.builtin_names():
        if name not in existing:
            session.add(ToolEntry(name=name, enabled=True))
    session.commit()

"""Agent 引用检查（specs/007-agent-management research R4）。

被模型 / Skill / MCP Server 管理模块的删除链路复用：
删除前反查 agent_bindings，命中即抛 ReferencedByAgentError（路由层转 409）。
检查必须在服务端执行（spec FR-027），不得只依赖前端禁用按钮。
"""

from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AgentBinding,
    AgentEntry,
    McpServerEntry,
    ModelEntry,
    SkillEntry,
    ToolEntry,
)

ResourceType = Literal["model", "tool", "skill", "mcp"]

# resource_type → (资源表, 资源名称属性)；主定义见 contracts/agents-api.md 枚举节
_RESOURCE_SOURCES: dict[str, tuple[type, str]] = {
    "model": (ModelEntry, "display_name"),
    "tool": (ToolEntry, "name"),
    "skill": (SkillEntry, "dir_name"),
    "mcp": (McpServerEntry, "name"),
}


class ReferencedByAgentError(Exception):
    """资源仍被 Agent 引用（路由层转 409）。

    resource_name 用于人话 detail；referenced_by：引用者列表 [{id, name}]。
    """

    def __init__(
        self,
        resource_name: str,
        referenced_by: list[dict[str, int | str]],
    ) -> None:
        self.resource_name = resource_name
        self.referenced_by = referenced_by
        names = "、".join(str(item.get("name")) for item in referenced_by)
        super().__init__(
            f"「{resource_name}」正被 Agent「{names}」使用，"
            "请先在对应 Agent 中移除绑定或更换模型后重试",
        )


def referenced_by_agents(
    session: Session, resource_type: ResourceType, resource_id: int,
) -> list[dict[str, int | str]]:
    """反查引用某资源的 Agent 列表（去重、按 id 升序）。

    模型引用有两个来源（SSOT：agents.model_id 列为主）：
    agents.model_id == resource_id，或 agent_bindings 中的 ("model", id) 行（防御性兜底）。
    """
    source = _RESOURCE_SOURCES.get(resource_type)
    if source is None:
        raise ValueError(f"非法的资源类型：{resource_type}")
    resource_table, _name_attr = source
    resource_exists = session.get(resource_table, resource_id)
    if resource_exists is None:
        return []
    conditions = [
        AgentBinding.resource_type == resource_type,
        AgentBinding.resource_id == resource_id,
    ]
    rows = session.execute(
        select(AgentEntry.id, AgentEntry.name)
        .join(AgentBinding, AgentBinding.agent_id == AgentEntry.id)
        .where(*conditions)
        .distinct()
        .order_by(AgentEntry.id),
    ).all()
    refs = [{"id": row.id, "name": row.name} for row in rows]
    if resource_type == "model":
        direct = session.scalars(
            select(AgentEntry)
            .where(AgentEntry.model_id == resource_id)
            .order_by(AgentEntry.id),
        ).all()
        seen = {ref["id"] for ref in refs}
        for entry in direct:
            if entry.id not in seen:
                refs.append({"id": entry.id, "name": entry.name})
    return refs


def assert_not_referenced_by_agent(
    session: Session, resource_type: ResourceType, resource_id: int, resource_name: str,
) -> list[dict[str, int | str]]:
    """资源被任意 Agent 引用时抛错（携带资源名与引用者列表）；未被引用时返回空列表。"""
    refs = referenced_by_agents(session, resource_type, resource_id)
    if refs:
        raise ReferencedByAgentError(resource_name, refs)
    return refs

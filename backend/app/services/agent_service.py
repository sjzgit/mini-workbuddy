"""Agent 管理业务逻辑：CRUD、提示词版本、默认一致性、删除流程、候选聚合。

规则来源：specs/007-agent-management/spec.md（FR-001~031）+ research.md R1–R8。
所有写操作单事务；默认唯一性由部分唯一索引 uq_agents_single_default 兜底。
"""

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AgentBinding,
    AgentEntry,
    AgentPromptVersion,
    McpServerEntry,
    ModelEntry,
    SkillEntry,
    ToolEntry,
)
from app.schemas.agents import (
    MAX_ROUNDS_DEFAULT,
    AgentOption,
    BindingItem,
    BindingOption,
    ModelOption,
    PromptVersionItem,
)
from app.schemas.agents import (
    AgentDetail,
    AgentListItem,
    AgentSaveRequest,
)
from app.services import skill_files
from app.services.agent_references import _RESOURCE_SOURCES
from app.services.skill_service import _load_compliant

# 系统提示词默认模板（契约"枚举与常量"节：主定义在此，经 binding-options 下发）
PROMPT_TEMPLATE = """# 角色：角色名称
角色概述和主要职责的一句话描述

## 目标：
角色的工作目标，如果有多目标可以分点列出，但建议更聚焦1-2个目标

## 技能：
1. 为了实现目标，角色需要具备的技能1"
2. 角色需要具备的技能2"

## 工作流：
1. 描述角色工作流程的第一步
2. 描述角色工作流程的第二步


## 输出格式：
如果对角色的输出格式有特定要求，可以在这里强调并举例说明想要的输出格式

## 限制：
- 描述角色在互动过程中需要遵循的限制条件1
"""


class AgentNotFoundError(LookupError):
    """Agent 不存在（路由层转 404）。"""


class RequiresNewDefaultError(Exception):
    """删除默认 Agent 但未提供合法新默认（路由层转 409 + requires_new_default）。

    candidates：其余 Agent 候选 [{id, name}]。
    """

    def __init__(self, candidates: list[AgentOption]) -> None:
        self.candidates = candidates
        super().__init__("该 Agent 是默认 Agent，请先选择新的默认 Agent")


class AgentValidationError(ValueError):
    """业务校验失败（路由层转 422）：模型不存在、绑定资源不存在等。"""


class AgentNameConflictError(Exception):
    """Agent 名称与已有 Agent 重复（路由层转 409）。

    payload 名单值；构造时由路由层生成人话 detail。
    """

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"已存在同名 Agent「{name}」，请换一个名称")


def _assert_name_unique(
    session: Session, name: str, exclude_agent_id: int | None,
) -> None:
    """名称全局唯一校验（编辑时排除自身）。"""
    query = select(AgentEntry).where(AgentEntry.name == name)
    if exclude_agent_id is not None:
        query = query.where(AgentEntry.id != exclude_agent_id)
    if session.scalar(query.limit(1)) is not None:
        raise AgentNameConflictError(name)


def _resource_name_description(
    session: Session, resource_type: str, resource_id: int,
) -> tuple[str, str, bool] | None:
    """读取资源的（名称, 说明, 启用状态）；资源已消失 → None（绑定仍返回但标记停用）。"""

    if resource_type == "tool":
        entry = session.get(ToolEntry, resource_id)
        if entry is None:
            return None
        from app.services.tool_registry import get_definition

        definition = get_definition(entry.name)
        description = definition.purpose if definition else ""
        return entry.name, description or "", entry.enabled
    if resource_type == "skill":
        entry = session.get(SkillEntry, resource_id)
        if entry is None:
            return None
        data = skill_files.read_skill(skill_files.skills_root() / entry.dir_name, entry.dir_name)
        if data is not None:
            return data.name, data.description or "", entry.enabled
        return entry.dir_name, "", entry.enabled
    if resource_type == "mcp":
        entry = session.get(McpServerEntry, resource_id)
        if entry is None:
            return None
        return entry.name, entry.description or "", entry.enabled
    return None


def _to_binding_item(
    session: Session, binding: AgentBinding,
) -> BindingItem | None:
    meta = _resource_name_description(session, binding.resource_type, binding.resource_id)
    if meta is None:
        # 资源行已消失（理论不可能：删除保护阻止；防御性兜底——丢弃该绑定展示）
        return None
    name, description, enabled = meta
    return BindingItem(
        resource_type=binding.resource_type,
        resource_id=binding.resource_id,
        name=name,
        description=description,
        enabled=enabled,
    )


_TYPE_ORDER = {"tool": 0, "skill": 1, "mcp": 2}


def _load_bindings(session: Session, agent_id: int) -> list[BindingItem]:
    """全部绑定（含停用，实时计算 enabled——research R6），tool→skill→mcp、id 升序。"""
    rows = session.scalars(
        select(AgentBinding)
        .where(AgentBinding.agent_id == agent_id)
        .order_by(AgentBinding.id),
    ).all()
    items = [item for item in (_to_binding_item(session, row) for row in rows) if item]
    items.sort(key=lambda item: (_TYPE_ORDER.get(item.resource_type, 9), item.resource_id))
    return items


def _to_detail(session: Session, entry: AgentEntry) -> AgentDetail:
    model = session.get(ModelEntry, entry.model_id)
    versions = session.scalars(
        select(AgentPromptVersion)
        .where(AgentPromptVersion.agent_id == entry.id)
        .order_by(AgentPromptVersion.version),
    ).all()
    return AgentDetail(
        id=entry.id,
        name=entry.name,
        description=entry.description,
        model_id=entry.model_id,
        model_display_name=model.display_name if model else "",
        model_identifier=model.model_identifier if model else "",
        system_prompt=entry.system_prompt,
        prompt_versions=[
            PromptVersionItem(
                version=v.version, content=v.content, created_at=v.created_at.isoformat(),
            )
            for v in versions
        ],
        bindings=_load_bindings(session, entry.id),
        max_rounds=entry.max_rounds,
        enable_deep_thinking=entry.enable_deep_thinking,
        thinking_level=entry.thinking_level,
        is_default=entry.is_default,
        updated_at=entry.updated_at.isoformat(),
    )


def list_agents(session: Session) -> list[AgentListItem]:
    """列表：默认 Agent 置顶，其余按 updated_at 倒序；绑定计数含停用，bindings 全量。"""
    entries = session.scalars(
        select(AgentEntry).order_by(
            AgentEntry.is_default.desc(),  # 默认置顶（至多一个，部分唯一索引保证）
            AgentEntry.updated_at.desc(),
            AgentEntry.id.desc(),
        ),
    ).all()
    items: list[AgentListItem] = []
    for entry in entries:
        model = session.get(ModelEntry, entry.model_id)
        bindings = _load_bindings(session, entry.id)
        counts = Counter(b.resource_type for b in bindings)
        items.append(
            AgentListItem(
                id=entry.id,
                name=entry.name,
                description=entry.description,
                model_display_name=model.display_name if model else "",
                model_identifier=model.model_identifier if model else "",
                tool_count=counts.get("tool", 0),
                skill_count=counts.get("skill", 0),
                mcp_count=counts.get("mcp", 0),
                bindings=bindings,
                is_default=entry.is_default,
                updated_at=updated_at_iso(entry.updated_at),
            ),
        )
    return items


def updated_at_iso(value: object) -> str:
    """updated_at → ISO 字符串（datetime/str 兼容）。"""
    if isinstance(value, str):
        return value
    return getattr(value, "isoformat")()


def get_agent(session: Session, agent_id: int) -> AgentDetail:
    """详情（FR-007 起的全部读取口径）。"""
    entry = session.get(AgentEntry, agent_id)
    if entry is None:
        raise AgentNotFoundError(f"Agent {agent_id} 不存在")
    return _to_detail(session, entry)


def _validate_bindings(
    session: Session,
    bindings: list,
) -> None:
    """保存前校验绑定资源存在且类型匹配（FR-016 之外的存在性校验）。"""
    for binding in bindings:
        source = _RESOURCE_SOURCES.get(binding.resource_type)
        if source is None:
            raise AgentValidationError(f"非法的资源类型：{binding.resource_type}")
        table, _ = source
        if session.get(table, binding.resource_id) is None:
            raise AgentValidationError(
                f"绑定的资源不存在：{binding.resource_type} #{binding.resource_id}",
            )


def _apply_default_on_save(
    session: Session, entry: AgentEntry, is_default_flag: bool, *, first_agent: bool,
) -> None:
    """默认位处理（FR-021/022）：首个 Agent 自动默认；显式 true 切换（先取消旧默认）。"""
    if first_agent:
        entry.is_default = True
        return
    if is_default_flag and not entry.is_default:
        current_default = session.scalar(
            select(AgentEntry).where(AgentEntry.is_default.is_(True)),
        )
        if current_default is not None and current_default.id != entry.id:
            current_default.is_default = False
            session.flush()
        entry.is_default = True


def redundant_default_hint(entry: AgentEntry, flag: bool) -> bool:
    """显式 true 时置位；false 保持现状（FR-021：有 Agent 时始终有默认）。"""
    return True if flag else entry.is_default


def save_agent(session: Session, payload: AgentSaveRequest, agent_id: int | None = None) -> AgentDetail:
    """新建（agent_id=None）或编辑（agent_id 给定），单事务完成全部写操作。

    版本规则（FR-018~020）：新建插 v1；编辑时仅当 system_prompt 与最新版本
    内容不同才追加 max+1；名称/模型/绑定/轮数变化不影响版本。
    绑定整体覆写（research R1）：提交集合为准，删旧插新。
    """
    model = session.get(ModelEntry, payload.model_id)
    if model is None:
        raise AgentValidationError("所选模型不存在，请重新选择")

    _assert_name_unique(session, payload.name, agent_id)

    if payload.bindings is not None:
        _validate_bindings(session, payload.bindings)

    creating = agent_id is None
    if creating:
        # 在插入前判定"是否首个 Agent"（flush 后自身已入库会污染 count）
        first_agent = session.scalar(select(func.count()).select_from(AgentEntry)) == 0
        entry = AgentEntry(
            name=payload.name,
            description=payload.description,
            model_id=payload.model_id,
            system_prompt=payload.system_prompt,
            max_rounds=payload.max_rounds,
            enable_deep_thinking=payload.enable_deep_thinking,
            thinking_level=payload.thinking_level,
        )
        session.add(entry)
        session.flush()  # 取 id
        session.add(
            AgentPromptVersion(agent_id=entry.id, version=1, content=payload.system_prompt),
        )
        _apply_default_on_save(session, entry, payload.is_default, first_agent=first_agent)
    else:
        entry = session.get(AgentEntry, agent_id)
        if entry is None:
            raise AgentNotFoundError(f"Agent {agent_id} 不存在")
        entry.name = payload.name
        entry.description = payload.description
        entry.model_id = payload.model_id
        entry.max_rounds = payload.max_rounds
        entry.enable_deep_thinking = payload.enable_deep_thinking
        entry.thinking_level = payload.thinking_level
        latest_version = session.scalar(
            select(AgentPromptVersion)
            .where(AgentPromptVersion.agent_id == entry.id)
            .order_by(AgentPromptVersion.version.desc())
            .limit(1),
        )
        if latest_version is None or latest_version.content != payload.system_prompt:
            next_version = (latest_version.version + 1) if latest_version else 1
            session.add(
                AgentPromptVersion(
                    agent_id=entry.id, version=next_version, content=payload.system_prompt,
                ),
            )
        entry.system_prompt = payload.system_prompt
        _apply_default_on_save(
            session, entry, payload.is_default, first_agent=False,
        )

    # 绑定保存：缺省（None）= 保持原绑定；给了集合 = 整体覆写（删旧插新，同一事务）
    if payload.bindings is not None:
        session.query(AgentBinding).filter(AgentBinding.agent_id == entry.id).delete()
        for binding in payload.bindings:
            session.add(
                AgentBinding(
                    agent_id=entry.id,
                    resource_type=binding.resource_type,
                    resource_id=binding.resource_id,
                ),
            )

    session.commit()
    session.refresh(entry)
    return _to_detail(session, entry)


def delete_agent(
    session: Session, agent_id: int, new_default_id: int | None,
) -> bool:
    """删除（FR-023~025）：默认+有其他+缺参 → RequiresNewDefaultError；
    删最后一个默认 → 清默认返回 True（页面回空状态）；与置新默认同一事务。
    """
    entry = session.get(AgentEntry, agent_id)
    if entry is None:
        raise AgentNotFoundError(f"Agent {agent_id} 不存在")

    others = session.scalars(
        select(AgentEntry).where(AgentEntry.id != agent_id).order_by(AgentEntry.id),
    ).all()
    if entry.is_default and others:
        if new_default_id is None:
            raise RequiresNewDefaultError(
                candidates=[AgentOption(id=o.id, name=o.name) for o in others],
            )
        successor = next((o for o in others if o.id == new_default_id), None)
        if successor is None:
            raise ValueError("新默认 Agent 不存在或不合法")
        # 先释放唯一索引占位，再设新默认（同一事务）
        entry.is_default = False
        session.flush()
        successor.is_default = True

    cleared_default = entry.is_default  # 到这里仍为 True ⇒ 删除的是最后一个（默认）Agent
    # 显式清理两张子表（SQLite PRAGMA foreign_keys 默认 OFF，DB 级 CASCADE 不生效；
    # 残留会使新 Agent 复用 id 后撞 agent_prompt_versions 唯一索引）
    session.query(AgentBinding).filter(AgentBinding.agent_id == agent_id).delete()
    session.query(AgentPromptVersion).filter(AgentPromptVersion.agent_id == agent_id).delete()
    session.delete(entry)
    session.commit()
    return cleared_default


def set_default(session: Session, agent_id: int) -> None:
    """设为默认（FR-022）：自动取消旧默认；已是默认 → 幂等成功。"""
    entry = session.get(AgentEntry, agent_id)
    if entry is None:
        raise AgentNotFoundError(f"Agent {agent_id} 不存在")
    if entry.is_default:
        return
    current = session.scalar(select(AgentEntry).where(AgentEntry.is_default.is_(True)))
    if current is not None:
        current.is_default = False
        session.flush()
    entry.is_default = True
    session.commit()


def get_binding_options(
    session: Session, agent_id: int | None = None,
) -> tuple[list[BindingOption], list[BindingOption], list[BindingOption], list[ModelOption], str]:
    """候选聚合（FR-013/014/016）：仅启用资源；编辑态 selected 回显；附提示词模板。"""
    agent_id_set: set[tuple[str, int]] = set()
    if agent_id is not None:
        rows = session.scalars(
            select(AgentBinding).where(AgentBinding.agent_id == agent_id),
        ).all()
        agent_id_set = {(b.resource_type, b.resource_id) for b in rows}

    from app.services.tool_registry import all_definitions

    definitions = {d.name: d for d in all_definitions()}
    tool_options: list[BindingOption] = []
    for entry in session.scalars(select(ToolEntry).where(ToolEntry.enabled.is_(True))).all():
        definition = definitions.get(entry.name)
        if definition is None:
            continue
        tool_options.append(
            BindingOption(
                id=entry.id,
                name=entry.name,
                description=definition.purpose or "",
                selected=("tool", entry.id) in agent_id_set,
            ),
        )

    skill_options: list[BindingOption] = []
    for entry, data in _load_compliant(session):
        if not entry.enabled:
            continue
        skill_options.append(
            BindingOption(
                id=entry.id,
                name=data.name,
                description=data.description or "",
                selected=("skill", entry.id) in agent_id_set,
            ),
        )

    mcp_options: list[BindingOption] = []
    for entry in session.scalars(
        select(McpServerEntry).where(McpServerEntry.enabled.is_(True)).order_by(McpServerEntry.id),
    ).all():
        mcp_options.append(
            BindingOption(
                id=entry.id,
                name=entry.name,
                description=entry.description or "",
                selected=("mcp", entry.id) in agent_id_set,
            ),
        )

    model_options = [
        ModelOption(
            id=m.id,
            display_name=m.display_name,
            model_identifier=m.model_identifier,
            is_default=m.is_default,
        )
        for m in session.scalars(select(ModelEntry).order_by(ModelEntry.id)).all()
    ]
    return tool_options, skill_options, mcp_options, model_options, PROMPT_TEMPLATE

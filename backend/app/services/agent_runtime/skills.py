"""Skill 目录组装与 load_skill 执行链（specs/009-agent-runtime 契约 §5）。

Skill 指令以文件为本体，读取唯一入口是 skill_files（FR-025：load_skill 不构成
绕过文件访问限制的入口——只按稳定标识（dir_name）读授权 Skill，拒绝路径形态输入）。
"""

import logging
from typing import TYPE_CHECKING

from app.core.config import settings
from app.services import skill_files
from app.services.skill_files import SkillFileData

if TYPE_CHECKING:
    from app.services.agent_runtime.tools import ToolCallOutcome, ToolContext

logger = logging.getLogger(__name__)

# Skill 专用错误码（契约 §4）
SKILL_NOT_FOUND = "skill_not_found"
SKILL_NOT_BOUND = "skill_not_bound"
SKILL_DISABLED = "skill_disabled"
SKILL_FILE_MISSING = "skill_file_missing"
SKILL_UNREADABLE = "skill_unreadable"
SKILL_TOO_LARGE = "skill_too_large"

_SKILL_ERROR_MESSAGES = {
    SKILL_NOT_FOUND: "Skill 不存在：{skill_id} 不在本次可用 Skill 目录中",
    SKILL_NOT_BOUND: "Skill 未绑定到当前 Agent：{skill_id}",
    SKILL_DISABLED: "Skill 已停用：{skill_id}。可在 Skills 管理页启用",
    SKILL_FILE_MISSING: "Skill 指令文件缺失：{skill_id}",
    SKILL_UNREADABLE: "Skill 指令无法读取：{skill_id}",
    SKILL_TOO_LARGE: (
        "Skill 指令超过大小上限（{limit} 字节），已拒绝加载：{skill_id}。"
        "请联系 Skill 维护者精简指令内容"
    ),
}

# 目录前置说明（契约 §5：固定包含按需加载指引）
CATALOG_GUIDE = (
    "以下是当前可用的 Skills 目录。当任务符合某个 Skill 的用途时，"
    "先调用 load_skill 工具加载其完整指令，再按照指令执行。"
)


def build_skill_catalog_section(catalog: list[dict[str, str]]) -> str:
    """目录条目 → 追加到系统提示词的 XML 片段（澄清指定格式，契约 §5）。

    catalog 条目：{"id": dir_name, "name": 名称, "description": 说明}。
    目录为空返回空串（调用方不追加）。
    """
    if not catalog:
        return ""
    blocks = []
    for item in catalog:
        blocks.append(
            f"<skill>\nName: {item['name']}\nID: {item['id']}\n"
            f"Description: {item['description']}\n</skill>"
        )
    return CATALOG_GUIDE + "\n\n" + "\n".join(blocks)


def _failure(code: str, skill_id: str) -> "ToolCallOutcome":
    """结构化失败（人话文案交还模型，不抛异常）。"""
    from app.services.agent_runtime.tools import ToolCallOutcome

    message = _SKILL_ERROR_MESSAGES[code].format(
        skill_id=skill_id, limit=settings.runtime_skill_max_bytes,
    )
    return ToolCallOutcome(success=False, error_code=code, message=message)


def load_skill(session, ctx, skill_id: str) -> "ToolCallOutcome":
    """load_skill 执行链：目录存在性 → DB 复核绑定+启用 → 读文件 → 上限校验。

    skill_id 必须是目录内的稳定标识（dir_name）；不接受任何文件路径形态输入
    （含 / \\ 与 .. 片段，FR-017）。成功时 instruction 放入 result_for_model。
    """
    from app.services.agent_runtime.tools import ToolCallOutcome
    from app.models import AgentBinding, SkillEntry

    skill_id = (skill_id or "").strip()

    # 路径形态输入直接拒绝（不读取任何文件）
    if (not skill_id or "/" in skill_id or "\\" in skill_id or ".." in skill_id):
        return _failure(SKILL_NOT_FOUND, skill_id or "<empty>")

    # ① 本次运行目录（含 limits 收窄结果）
    if skill_id not in ctx.skill_catalog_ids:
        return _failure(SKILL_NOT_FOUND, skill_id)

    # ② 执行前 DB 复核：绑定关系 + 启用状态（FR-016）
    agent_id = ctx.run_request.agent_id
    skill = session.query(SkillEntry).filter(SkillEntry.dir_name == skill_id).first()
    if skill is None:
        return _failure(SKILL_NOT_FOUND, skill_id)
    bound = session.scalar(
        session.query(AgentBinding.id).filter(
            AgentBinding.agent_id == agent_id,
            AgentBinding.resource_type == "skill",
            AgentBinding.resource_id == skill.id,
        ).limit(1)
    )
    if bound is None:
        return _failure(SKILL_NOT_BOUND, skill_id)
    if not skill.enabled:
        return _failure(SKILL_DISABLED, skill_id)

    # ③ 读指令（skill_files 宽松读；目录缺失/文件缺失/不可读分档）
    data: SkillFileData | None = skill_files.read_skill(
        skill_files.skills_root() / skill_id, skill_id,
    )
    if data is None:
        target = skill_files.skills_root() / skill_id / skill_files.SKILL_FILE_NAME
        if not target.is_file():
            return _failure(SKILL_FILE_MISSING, skill_id)
        return _failure(SKILL_UNREADABLE, skill_id)

    # ④ 大小上限：明确报错，不静默截断（FR-019）
    encoded = data.instruction.encode("utf-8")
    if len(encoded) > settings.runtime_skill_max_bytes:
        return _failure(SKILL_TOO_LARGE, skill_id)

    return ToolCallOutcome(success=True, result_for_model=data.instruction)

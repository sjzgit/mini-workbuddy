"""三类快照构建与状态机校验（specs/012，data-model.md §3/§4）。

快照在任务创建时一次性固化，之后任何路径不更新（Invariant 5/6/7）。
结构变更先改 data-model.md，再同步本文件与测试。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AgentBinding,
    AgentEntry,
    EvaluationCaseEntry,
    EvaluationDatasetEntry,
    EvaluationRunEntry,
    McpServerEntry,
    ModelEntry,
    SkillEntry,
    ToolEntry,
)
from app.schemas.evaluation import RUN_STATUS_TRANSITIONS


class SnapshotBuildError(ValueError):
    """快照构建失败（源资源缺失/配置非法，路由层转 422）。"""


def new_run_uuid() -> str:
    """评测运行业务标识（uuid4 hex，与 AgentRun run_id 同格式异命名空间）。"""
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    """与 models._utcnow 同口径：naive UTC、去微秒。"""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


# ---- Agent 快照（data-model.md §3.1）----


def build_agent_snapshot(session: Session, agent_id: int) -> dict:
    """固化 Agent 当前配置（含模型、绑定与运行时配置）。

    执行语义（research D3）：快照为记录与呈现；执行读取当前库配置。
    """
    agent = session.get(AgentEntry, agent_id)
    if agent is None:
        raise SnapshotBuildError(f"Agent {agent_id} 不存在")
    model = session.get(ModelEntry, agent.model_id)
    if model is None:
        raise SnapshotBuildError(f"Agent {agent_id} 绑定的模型不存在")

    tool_rows = session.execute(
        select(ToolEntry.name)
        .join(AgentBinding, (AgentBinding.resource_id == ToolEntry.id)
              & (AgentBinding.resource_type == "tool"))
        .where(AgentBinding.agent_id == agent_id, ToolEntry.enabled == True)  # noqa: E712
    ).scalars().all()

    from app.services.tool_registry import all_definitions
    from app.services.agent_runtime.tools import _schema_from_params_model

    definitions = {d.name: d for d in all_definitions()}
    tools_snapshot = [
        {"name": name,
         "description": definitions[name].purpose if name in definitions else "",
         "parameters": (
             _schema_from_params_model(definitions[name].params_model)
             if name in definitions else {}
         )}
        for name in sorted(tool_rows)
    ]

    skill_rows = session.execute(
        select(SkillEntry)
        .join(AgentBinding, (AgentBinding.resource_id == SkillEntry.id)
              & (AgentBinding.resource_type == "skill"))
        .where(AgentBinding.agent_id == agent_id, SkillEntry.enabled == True)  # noqa: E712
    ).scalars().all()
    skills_snapshot = [
        {"id": skill.dir_name, "name": skill.dir_name, "description": ""}
        for skill in sorted(skill_rows, key=lambda s: s.dir_name)
    ]

    mcp_rows = session.execute(
        select(McpServerEntry)
        .join(AgentBinding, (AgentBinding.resource_id == McpServerEntry.id)
              & (AgentBinding.resource_type == "mcp"))
        .where(AgentBinding.agent_id == agent_id, McpServerEntry.enabled == True)  # noqa: E712
    ).scalars().all()
    from app.services import mcp_client
    mcp_snapshot = [
        {"id": server.id, "name": server.name,
         "tools": [t.name for t in mcp_client.loads_tools(server.tools_json)]}
        for server in sorted(mcp_rows, key=lambda s: s.id)
    ]

    return {
        "agent_id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "model": {
            "model_id": model.id,
            "display_name": model.display_name,
            "model_identifier": model.model_identifier,
            "base_url": model.base_url,
            "temperature": float(model.temperature),
            "max_output_tokens": model.max_output_tokens,
            "enable_deep_thinking": bool(agent.enable_deep_thinking),
            "thinking_level": agent.thinking_level,
        },
        "max_rounds": agent.max_rounds,
        "skills": skills_snapshot,
        "tools": tools_snapshot,
        "mcp_servers": mcp_snapshot,
        "runtime": {
            "auto_compact": bool(agent.auto_compact),
            "compact_trigger_ratio": float(agent.compact_trigger_ratio),
            "compact_keep_recent_rounds": agent.compact_keep_recent_rounds,
            "compact_summary_target_tokens": agent.compact_summary_target_tokens,
        },
    }


# ---- 数据集快照（data-model.md §3.2）----


def build_dataset_snapshot(session: Session, dataset_id: int) -> dict:
    """固化数据集与全部 Case 内容（评测执行的真正输入，FR-007）。"""
    dataset = session.get(EvaluationDatasetEntry, dataset_id)
    if dataset is None:
        raise SnapshotBuildError(f"数据集 {dataset_id} 不存在")
    cases = session.scalars(
        select(EvaluationCaseEntry)
        .where(EvaluationCaseEntry.dataset_id == dataset_id)
        .order_by(EvaluationCaseEntry.id)
    ).all()
    return {
        "dataset_id": dataset.id,
        "name": dataset.name,
        "description": dataset.description,
        "cases": [
            {
                "case_id": case.id,
                "user_question": case.user_question,
                "expected_answer": case.expected_answer,
                "scoring_criteria": case.scoring_criteria,
            }
            for case in cases
        ],
    }


# ---- 评分器快照（data-model.md §3.3）----


def build_evaluator_snapshot(
    session: Session,
    evaluator_type: str,
    evaluator_config: dict,
    pass_threshold: int,
) -> dict:
    """固化评分器配置（llm_judge 需要模型存在）。"""
    snapshot: dict = {
        "type": evaluator_type,
        "model_model_id": None,
        "model_display_name": None,
        "temperature": None,
        "max_tokens": None,
        "prompt_template": None,
        "pass_threshold": pass_threshold,
        "config": dict(evaluator_config),
    }
    if evaluator_type == "llm_judge":
        from app.schemas.evaluation import (
            JUDGE_DEFAULT_MAX_TOKENS,
            JUDGE_DEFAULT_TEMPERATURE,
        )

        model_id = evaluator_config.get("model_model_id")
        if not isinstance(model_id, int):
            raise SnapshotBuildError("llm_judge 评分器必须提供 model_model_id")
        model = session.get(ModelEntry, model_id)
        if model is None:
            raise SnapshotBuildError(f"评分模型 {model_id} 不存在")
        snapshot["model_model_id"] = model.id
        snapshot["model_display_name"] = model.display_name
        snapshot["temperature"] = float(
            evaluator_config.get("temperature", JUDGE_DEFAULT_TEMPERATURE))
        snapshot["max_tokens"] = int(
            evaluator_config.get("max_tokens", JUDGE_DEFAULT_MAX_TOKENS))
        snapshot["prompt_template"] = evaluator_config.get("prompt_template")
    return snapshot


# ---- 状态机（data-model.md §4.2）----


def run_status_can(from_status: str, to_status: str) -> bool:
    """评测运行状态机合法跳转判定（FR-023 防非法跳转）。"""
    return to_status in RUN_STATUS_TRANSITIONS.get(from_status, ())


def transition_run_status(entry: EvaluationRunEntry, to_status: str) -> None:
    """合法跳转时更新状态；非法跳转抛 ValueError（Invariant：防非法状态）。"""
    if not run_status_can(entry.status, to_status):
        raise ValueError(f"评测运行不允许从 {entry.status} 跳转到 {to_status}")
    entry.status = to_status

"""评测任务快照测试（specs/012 US2，FR-004~008 / Invariant 5/6/7）。"""

import pytest

from app.services.evaluation import dataset_service, task_service
from app.services.evaluation.snapshots import (
    build_agent_snapshot,
    build_dataset_snapshot,
    build_evaluator_snapshot,
)


@pytest.fixture
def dataset_with_cases(db_session):
    ds = dataset_service.create_dataset(db_session, "快照数据集", "")
    dataset_service.import_cases(db_session, ds.id, {
        "name": "x", "cases": [
            {"user_question": "q1", "expected_answer": "a1",
             "scoring_criteria": "c1"},
            {"user_question": "q2"},
        ],
    })
    return ds


@pytest.fixture
def a_task(db_session, seed_agent, dataset_with_cases):
    return task_service.create_task(
        db_session, "基线评测", seed_agent.id, dataset_with_cases.id,
        "exact_match", {}, 80,
    )


def test_create_task_snapshots(db_session, seed_agent, dataset_with_cases, a_task):
    assert a_task.case_count == 2
    # Agent 快照逐字段对应当前配置
    assert a_task.agent_snapshot["name"] == seed_agent.name
    assert a_task.agent_snapshot["system_prompt"] == seed_agent.system_prompt
    assert a_task.agent_snapshot["model"]["model_id"] == seed_agent.model_id
    assert a_task.agent_snapshot["max_rounds"] == seed_agent.max_rounds
    # 数据集快照含全部 Case 原文
    assert len(a_task.dataset_snapshot["cases"]) == 2
    # 评分器快照固化阈值与类型
    assert a_task.evaluator_snapshot["type"] == "exact_match"
    assert a_task.evaluator_snapshot["pass_threshold"] == 80


def test_snapshot_immutable_after_source_changes(
    db_session, seed_agent, dataset_with_cases, a_task,
):
    """修改 Agent 与数据集后任务快照不变（Invariant 5/6）。"""
    from app.models import AgentEntry, EvaluationCaseEntry

    agent = db_session.get(AgentEntry, seed_agent.id)
    agent.system_prompt = "已被修改的提示词"
    db_session.commit()
    case = db_session.query(EvaluationCaseEntry).filter_by(
        dataset_id=dataset_with_cases.id,
    ).first()
    case.user_question = "已被修改的问题"
    db_session.commit()

    detail = task_service.get_task(db_session, a_task.id)
    assert detail.agent_snapshot["system_prompt"] == "你是一个测试助手。"
    assert detail.dataset_snapshot["cases"][0]["user_question"] == "q1"


def test_llm_judge_config_validation(db_session, seed_agent, dataset_with_cases):
    # 缺 model_model_id → 422
    with pytest.raises(task_service.TaskValidationError):
        task_service.create_task(
            db_session, "t", seed_agent.id, dataset_with_cases.id,
            "llm_judge", {}, 80,
        )
    # exact_match 带模型配置同样合法（仅快照按 type 字段固化，额外键忽略进 config）
    task = task_service.create_task(
        db_session, "t2", seed_agent.id, dataset_with_cases.id,
        "llm_judge", {"model_model_id": seed_agent.model_id,
                      "temperature": 0.1, "max_tokens": 512}, 60,
    )
    assert task.evaluator_snapshot["model_model_id"] == seed_agent.model_id
    assert task.evaluator_snapshot["temperature"] == 0.1


def test_create_task_invalid_inputs(db_session, seed_agent, dataset_with_cases):
    with pytest.raises(task_service.TaskValidationError):
        task_service.create_task(
            db_session, "t", 99999, dataset_with_cases.id, "exact_match", {}, 80,
        )
    with pytest.raises(task_service.TaskValidationError):
        task_service.create_task(
            db_session, "t", seed_agent.id, 99999, "exact_match", {}, 80,
        )
    # 空数据集：新建一个无 Case 的数据集
    empty = dataset_service.create_dataset(db_session, "空数据集", "")
    with pytest.raises(task_service.TaskValidationError):
        task_service.create_task(
            db_session, "t", seed_agent.id, empty.id, "exact_match", {}, 80,
        )
    # 阈值越界由 Pydantic 契约拦截（此处 service 层不重复校验，验证超范围值直传的拒绝在 API 层）
    from pydantic import ValidationError

    from app.schemas.evaluation import TaskSaveRequest

    with pytest.raises(ValidationError):
        TaskSaveRequest(
            name="t", agent_id=seed_agent.id, dataset_id=dataset_with_cases.id,
            evaluator_type="exact_match", pass_threshold=150,
        )


def test_delete_task_cascades(db_session, seed_agent, dataset_with_cases, a_task):
    from app.services.evaluation import run_service as eval_run_service

    eval_run_service.create_run_for_task(db_session, a_task.id)
    task_service.delete_task(db_session, a_task.id)
    with pytest.raises(task_service.TaskNotFoundError):
        task_service.get_task(db_session, a_task.id)
    from sqlalchemy import select

    from app.models import EvaluationRunEntry

    assert db_session.scalars(
        select(EvaluationRunEntry).where(EvaluationRunEntry.task_id == a_task.id),
    ).all() == []

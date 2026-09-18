"""数据集服务：数据集/Case CRUD 与 JSON 导入导出（specs/012，US1，FR-001~003）。

契约主定义：specs/012-agent-evaluation/contracts/evaluation-api.md §1-§3
导入为整体校验：任一非法即整体拒绝，不产生部分导入（FR-003）。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import EvaluationCaseEntry, EvaluationDatasetEntry
from app.schemas.evaluation import CaseOut, DatasetOut, ImportResult


class DatasetNotFoundError(LookupError):
    """数据集不存在（路由层转 404）。"""


class DatasetCaseNotFoundError(LookupError):
    """数据集用例不存在（路由层转 404）。"""


class DatasetValidationError(ValueError):
    """数据集/用例业务校验失败（路由层转 422）。"""


class ImportValidationError(ValueError):
    """JSON 导入整体校验失败（携带逐条定位错误，路由层转 422）。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("；".join(errors[:5]) + ("…" if len(errors) > 5 else ""))
        self.errors = errors


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _to_dataset_out(session: Session, entry: EvaluationDatasetEntry) -> DatasetOut:
    count = session.scalar(
        select(func.count(EvaluationCaseEntry.id))
        .where(EvaluationCaseEntry.dataset_id == entry.id)
    )
    return DatasetOut(
        id=entry.id,
        name=entry.name,
        description=entry.description,
        case_count=int(count or 0),
        created_at=entry.created_at.isoformat(),
        updated_at=entry.updated_at.isoformat(),
    )


def _to_case_out(entry: EvaluationCaseEntry) -> CaseOut:
    return CaseOut(
        id=entry.id,
        dataset_id=entry.dataset_id,
        user_question=entry.user_question,
        expected_answer=entry.expected_answer,
        scoring_criteria=entry.scoring_criteria,
        created_at=entry.created_at.isoformat(),
        updated_at=entry.updated_at.isoformat(),
    )


def _get_dataset(session: Session, dataset_id: int) -> EvaluationDatasetEntry:
    entry = session.get(EvaluationDatasetEntry, dataset_id)
    if entry is None:
        raise DatasetNotFoundError(f"数据集 {dataset_id} 不存在")
    return entry


def _get_case(
    session: Session, dataset_id: int, case_id: int,
) -> EvaluationCaseEntry:
    _get_dataset(session, dataset_id)
    entry = session.get(EvaluationCaseEntry, case_id)
    if entry is None or entry.dataset_id != dataset_id:
        raise DatasetCaseNotFoundError(f"用例 {case_id} 不存在")
    return entry


# ---- 数据集 CRUD（契约 §1）----


def create_dataset(session: Session, name: str, description: str) -> DatasetOut:
    entry = EvaluationDatasetEntry(
        name=name.strip(), description=description or "",
    )
    session.add(entry)
    session.commit()
    return _to_dataset_out(session, entry)


def list_datasets(session: Session) -> list[DatasetOut]:
    entries = session.scalars(
        select(EvaluationDatasetEntry)
        .order_by(EvaluationDatasetEntry.updated_at.desc(),
                  EvaluationDatasetEntry.id.desc())
    ).all()
    return [_to_dataset_out(session, entry) for entry in entries]


def get_dataset(session: Session, dataset_id: int) -> DatasetOut:
    return _to_dataset_out(session, _get_dataset(session, dataset_id))


def update_dataset(
    session: Session, dataset_id: int, name: str, description: str,
) -> DatasetOut:
    entry = _get_dataset(session, dataset_id)
    entry.name = name.strip()
    entry.description = description or ""
    entry.updated_at = _utcnow()
    session.commit()
    return _to_dataset_out(session, entry)


def delete_dataset(session: Session, dataset_id: int) -> None:
    """删除数据集并级联删 Case；历史运行读任务快照不受影响（FR-007）。"""
    entry = _get_dataset(session, dataset_id)
    session.delete(entry)
    session.commit()


# ---- Case CRUD（契约 §2）----


def list_cases(session: Session, dataset_id: int) -> list[CaseOut]:
    _get_dataset(session, dataset_id)
    entries = session.scalars(
        select(EvaluationCaseEntry)
        .where(EvaluationCaseEntry.dataset_id == dataset_id)
        .order_by(EvaluationCaseEntry.id)
    ).all()
    return [_to_case_out(entry) for entry in entries]


def create_case(
    session: Session, dataset_id: int,
    user_question: str,
    expected_answer: str | None,
    scoring_criteria: str | None,
) -> CaseOut:
    _get_dataset(session, dataset_id)
    entry = EvaluationCaseEntry(
        dataset_id=dataset_id,
        user_question=user_question.strip(),
        expected_answer=expected_answer,
        scoring_criteria=scoring_criteria,
    )
    session.add(entry)
    session.commit()
    return _to_case_out(entry)


def update_case(
    session: Session, dataset_id: int, case_id: int,
    user_question: str,
    expected_answer: str | None,
    scoring_criteria: str | None,
) -> CaseOut:
    entry = _get_case(session, dataset_id, case_id)
    entry.user_question = user_question.strip()
    entry.expected_answer = expected_answer
    entry.scoring_criteria = scoring_criteria
    entry.updated_at = _utcnow()
    session.commit()
    return _to_case_out(entry)


def delete_case(session: Session, dataset_id: int, case_id: int) -> None:
    entry = _get_case(session, dataset_id, case_id)
    session.delete(entry)
    session.commit()


# ---- JSON 导入导出（契约 §3，FR-003）----


def _validate_import_payload(payload: object) -> list[dict]:
    """整体校验导入 JSON；非法项收集为带定位的错误列表（任一非法即整体拒绝）。"""
    errors: list[str] = []
    if not isinstance(payload, dict):
        raise ImportValidationError(["导入内容必须是 JSON 对象"])
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("name：必填且须为非空字符串")
    if "description" in payload and payload.get("description") is not None \
            and not isinstance(payload.get("description"), str):
        errors.append("description：须为字符串或 null")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        errors.append("cases：必填且须为数组")
        raise ImportValidationError(errors)
    if len(cases) == 0:
        errors.append("cases：不能为空数组")
    for index, raw in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(raw, dict):
            errors.append(f"{prefix}：须为对象")
            continue
        question = raw.get("user_question")
        if not isinstance(question, str) or not question.strip():
            errors.append(f"{prefix}.user_question：必填且须为非空字符串")
        for field in ("expected_answer", "scoring_criteria"):
            value = raw.get(field)
            if field in raw and value is not None and not isinstance(value, str):
                errors.append(f"{prefix}.{field}：须为字符串或 null")
    if errors:
        raise ImportValidationError(errors)
    return [
        {
            "user_question": str(case["user_question"]).strip(),
            "expected_answer": case.get("expected_answer"),
            "scoring_criteria": case.get("scoring_criteria"),
        }
        for case in cases
        if isinstance(case, dict)
    ]


def import_cases(session: Session, dataset_id: int, payload: object) -> ImportResult:
    """整体校验通过后追加导入（不覆盖已有 Case，契约 §3）。"""
    _get_dataset(session, dataset_id)
    valid_cases = _validate_import_payload(payload)
    for item in valid_cases:
        session.add(EvaluationCaseEntry(dataset_id=dataset_id, **item))
    dataset = _get_dataset(session, dataset_id)
    dataset.updated_at = _utcnow()
    session.commit()
    return ImportResult(imported_cases=len(valid_cases))


def export_dataset(session: Session, dataset_id: int) -> dict:
    """导出契约 §9 格式（不含 case_id，可回导）。"""
    entry = _get_dataset(session, dataset_id)
    cases = session.scalars(
        select(EvaluationCaseEntry)
        .where(EvaluationCaseEntry.dataset_id == dataset_id)
        .order_by(EvaluationCaseEntry.id)
    ).all()
    return {
        "name": entry.name,
        "description": entry.description,
        "cases": [
            {
                "user_question": case.user_question,
                "expected_answer": case.expected_answer,
                "scoring_criteria": case.scoring_criteria,
            }
            for case in cases
        ],
    }

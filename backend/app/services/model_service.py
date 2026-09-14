"""模型管理业务逻辑：CRUD、默认模型一致性、测试连接分类。

规则来源：specs/002-model-management/spec.md（FR-001~023）+ research.md R2/R4。
所有写操作单事务；默认唯一性由部分唯一索引 uq_models_single_default 兜底。
"""

from decimal import Decimal

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core import secret_vault
from app.models import ModelEntry
from app.schemas.model import (
    REPLY_EXCERPT_MAX_CHARS,
    ModelDetail,
    ModelItem,
    ModelUpsertRequest,
    TestConnectionResult,
)
from app.schemas.model import TestErrorCategory
from app.services import agent_references, openai_client
from app.services.openai_client import BadResponseFormatError, ChatHttpError

# 测试连接失败提示模板（契约主定义，前端原样展示）
_TEST_MESSAGES = {
    "auth_error": "认证失败：API Key 无效或无权限。请核对密钥是否正确、是否过期。",
    "model_not_found": "模型标识不存在：服务端不认识该 model 名称。请核对与服务商提供的模型标识是否一致。",
    "unreachable": "服务地址不可访问。请检查地址是否可达、是否需要 VPN/内网、/v1 写法是否正确（示例：https://api.example.com/v1）。",
    "timeout": "请求超时（30 秒）。请检查网络状况或服务端负载。",
    "bad_response": "服务返回了无法识别的内容。该地址可能不是 OpenAI Chat Completions 兼容接口。",
    "unknown": "连接失败，暂时无法确定原因。请稍后重试或检查模型配置。",
}


class ModelNotFoundError(LookupError):
    """模型不存在（路由层转 404）。"""


class DefaultSwitchError(ValueError):
    """删除默认模型时未提供合法的新默认（路由层转 400）。"""


def _to_item(session: Session, entry: ModelEntry) -> ModelItem:
    return ModelItem(
        id=entry.id,
        display_name=entry.display_name,
        model_identifier=entry.model_identifier,
        base_url=entry.base_url,
        context_length=entry.context_length,
        api_key_configured=secret_vault.has_secret(session, entry.secret_ref),
        is_default=entry.is_default,
        updated_at=entry.updated_at.isoformat(),
    )


def _to_detail(session: Session, entry: ModelEntry) -> ModelDetail:
    return ModelDetail(
        **_to_item(session, entry).model_dump(),
        max_output_tokens=entry.max_output_tokens,
        temperature=entry.temperature,
        input_price=entry.input_price,
        output_price=entry.output_price,
        cached_input_price=entry.cached_input_price,
    )


def list_models(session: Session) -> list[ModelItem]:
    """列表（按更新时间倒序）。"""
    entries = session.scalars(
        select(ModelEntry).order_by(ModelEntry.updated_at.desc(), ModelEntry.id.desc()),
    ).all()
    return [_to_item(session, entry) for entry in entries]


def get_model(session: Session, model_id: int) -> ModelDetail:
    entry = session.get(ModelEntry, model_id)
    if entry is None:
        raise ModelNotFoundError(f"模型 {model_id} 不存在")
    return _to_detail(session, entry)


def create_model(session: Session, payload: ModelUpsertRequest) -> ModelDetail:
    """新增：密钥加密入库；当前无默认模型时自动设为默认（FR-018）。"""
    entry = ModelEntry(
        display_name=payload.display_name,
        model_identifier=payload.model_identifier,
        base_url=payload.base_url,
        context_length=payload.context_length,
        max_output_tokens=payload.max_output_tokens,
        temperature=payload.temperature.quantize(Decimal("0.1")),
        input_price=payload.input_price,
        output_price=payload.output_price,
        cached_input_price=payload.cached_input_price,
        is_default=_has_no_default(session),
    )
    session.add(entry)
    session.flush()  # 先拿到 id，再挂密钥
    entry.secret_ref = secret_vault.store_secret(session, None, payload.api_key or "")
    session.commit()
    return _to_detail(session, entry)


def update_model(session: Session, model_id: int, payload: ModelUpsertRequest) -> ModelDetail:
    """编辑：密钥留空保留原值（FR-012）；不改 is_default。"""
    entry = session.get(ModelEntry, model_id)
    if entry is None:
        raise ModelNotFoundError(f"模型 {model_id} 不存在")
    entry.display_name = payload.display_name
    entry.model_identifier = payload.model_identifier
    entry.base_url = payload.base_url
    entry.context_length = payload.context_length
    entry.max_output_tokens = payload.max_output_tokens
    entry.temperature = payload.temperature.quantize(Decimal("0.1"))
    entry.input_price = payload.input_price
    entry.output_price = payload.output_price
    entry.cached_input_price = payload.cached_input_price
    entry.secret_ref = secret_vault.store_secret(session, entry.secret_ref, payload.api_key or "")
    session.add(entry)
    session.commit()
    return _to_detail(session, entry)


def set_default(session: Session, model_id: int) -> None:
    """设默认：同事务翻转旧默认（FR-019），部分唯一索引兜底唯一性。"""
    entry = session.get(ModelEntry, model_id)
    if entry is None:
        raise ModelNotFoundError(f"模型 {model_id} 不存在")
    session.execute(
        update(ModelEntry).where(ModelEntry.id != model_id).values(is_default=False),
    )
    entry.is_default = True
    session.add(entry)
    session.commit()


def delete_model(session: Session, model_id: int, new_default_id: int | None) -> None:
    """删除：默认模型 + 仍有其他模型时必须提供合法 new_default_id（FR-020/021）。

    Agent 引用检查在最前（007 FR-029：先查引用，再走默认切换规则）。
    同事务完成"清默认位 → 设新默认 → 删除 + 清理密钥"，避免中间态。
    """
    entry = session.get(ModelEntry, model_id)
    if entry is None:
        raise ModelNotFoundError(f"模型 {model_id} 不存在")

    # Agent 引用保护（specs/007 US6）：被引用即拒绝，不触发默认切换
    agent_references.assert_not_referenced_by_agent(session, "model", model_id, entry.display_name)

    others_count = session.scalar(
        select(func.count()).select_from(ModelEntry).where(ModelEntry.id != model_id),
    )
    if entry.is_default and others_count:
        if new_default_id is None:
            raise DefaultSwitchError("删除默认模型前需要选择新的默认模型")
        if new_default_id == model_id:
            raise DefaultSwitchError("新默认模型不能是被删除的模型")
        successor = session.get(ModelEntry, new_default_id)
        if successor is None:
            raise DefaultSwitchError("新默认模型不存在")
        # 先释放唯一索引占位，再设新默认（同一事务，外部不可见中间态）
        entry.is_default = False
        session.flush()
        successor.is_default = True

    secret_vault.delete_secret(session, entry.secret_ref)
    session.delete(entry)
    session.commit()


def test_connection(session: Session, model_id: int) -> TestConnectionResult:
    """测试连接：真实请求 + 五类错误分类（research R4）。"""
    entry = session.get(ModelEntry, model_id)
    if entry is None:
        raise ModelNotFoundError(f"模型 {model_id} 不存在")

    api_key = secret_vault.load_secret(session, entry.secret_ref)
    try:
        reply = openai_client.send_test_message(entry.base_url, entry.model_identifier, api_key)
    except ChatHttpError as exc:
        category = _classify_http_error(exc)
        return TestConnectionResult(
            success=False, category=category, message=_TEST_MESSAGES[category],
        )
    except httpx.TimeoutException:
        return TestConnectionResult(
            success=False, category="timeout", message=_TEST_MESSAGES["timeout"],
        )
    except BadResponseFormatError:
        return TestConnectionResult(
            success=False, category="bad_response", message=_TEST_MESSAGES["bad_response"],
        )
    except httpx.HTTPError:
        return TestConnectionResult(
            success=False, category="unreachable", message=_TEST_MESSAGES["unreachable"],
        )
    except Exception:  # noqa: BLE001 — 无法归类的失败如实说明，不泄露堆栈
        return TestConnectionResult(
            success=False, category="unknown", message=_TEST_MESSAGES["unknown"],
        )
    return TestConnectionResult(
        success=True,
        message="模型已连接",
        reply_excerpt=reply.content[:REPLY_EXCERPT_MAX_CHARS],
    )


def _classify_http_error(exc: ChatHttpError) -> TestErrorCategory:
    """按状态码与响应体片段映射错误类别（不含请求侧信息，无密钥泄露面）。"""
    if exc.status_code in (401, 403):
        return "auth_error"
    body = exc.body_snippet.lower()
    if exc.status_code == 404 and ("model" in body or "not found" in body):
        return "model_not_found"
    if exc.status_code == 404:
        return "unreachable"
    return "unreachable" if 400 <= exc.status_code < 600 else "unknown"


def _has_no_default(session: Session) -> bool:
    """当前是否存在默认模型（新增自动默认的判断）。"""
    count = session.scalar(
        select(func.count()).select_from(ModelEntry).where(ModelEntry.is_default),
    )
    return not count

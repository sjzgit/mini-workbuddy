"""业务规则测试：默认模型一致性、密钥库、删除清理（US3/US4 核心）。"""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import secret_vault
from app.models import ModelEntry, SecretVaultEntry
from app.schemas.model import ModelDetail, ModelUpsertRequest
from app.services import model_service
from app.services.model_service import DefaultSwitchError, ModelNotFoundError


def make_request(**overrides: Any) -> ModelUpsertRequest:
    payload: dict[str, Any] = {
        "display_name": "模型A",
        "model_identifier": "gpt-a",
        "base_url": "https://a.example.com/v1/",
        "api_key": None,
        "context_length": 8192,
        "max_output_tokens": 4096,
        "temperature": Decimal("0.7"),
        "input_price": None,
        "output_price": None,
        "cached_input_price": None,
    }
    payload.update(overrides)
    return ModelUpsertRequest(**payload)


def create(db_session: Session, name: str = "A", **overrides: Any) -> ModelDetail:
    return model_service.create_model(db_session, make_request(display_name=name, **overrides))


# ---- 默认模型生命周期（FR-017~019）----


def test_first_model_auto_default(db_session: Session) -> None:
    first = create(db_session, "A")
    second = create(db_session, "B")
    assert first.is_default is True
    assert second.is_default is False


def test_set_default_flips_exclusively(db_session: Session) -> None:
    first = create(db_session, "A")
    second = create(db_session, "B")
    model_service.set_default(db_session, second.id)
    first_entry = db_session.get(ModelEntry, first.id)
    second_entry = db_session.get(ModelEntry, second.id)
    assert first_entry is not None and first_entry.is_default is False
    assert second_entry is not None and second_entry.is_default is True


def test_partial_unique_index_blocks_double_default(db_session: Session) -> None:
    """数据库层兜底：任何途径造成双默认都会被索引拒绝（research R2）。"""
    create(db_session, "A")
    create(db_session, "B")
    with pytest.raises(IntegrityError):
        db_session.execute(text("UPDATE models SET is_default = 1"))
    db_session.rollback()


def test_set_default_unknown_raises(db_session: Session) -> None:
    with pytest.raises(ModelNotFoundError):
        model_service.set_default(db_session, 999)


# ---- 删除流程（FR-020/021）----


def test_delete_normal_model_keeps_default(db_session: Session) -> None:
    first = create(db_session, "A")
    second = create(db_session, "B")
    model_service.delete_model(db_session, second.id, None)
    first_entry = db_session.get(ModelEntry, first.id)
    assert first_entry is not None and first_entry.is_default is True
    assert model_service.list_models(db_session)[0].id == first.id


def test_delete_default_requires_successor(db_session: Session) -> None:
    first = create(db_session, "A")
    create(db_session, "B")
    with pytest.raises(DefaultSwitchError):
        model_service.delete_model(db_session, first.id, None)


def test_delete_default_rejects_self_or_unknown_successor(db_session: Session) -> None:
    first = create(db_session, "A")
    create(db_session, "B")
    with pytest.raises(DefaultSwitchError):
        model_service.delete_model(db_session, first.id, first.id)
    with pytest.raises(DefaultSwitchError):
        model_service.delete_model(db_session, first.id, 999)


def test_delete_default_with_successor_switches_and_cleans_secret(
    db_session: Session, secret_key_path: Path,
) -> None:
    first = create(db_session, "A", api_key="sk-default-key")
    second = create(db_session, "B")
    secret_ref = db_session.get(ModelEntry, first.id).secret_ref
    assert secret_ref is not None

    model_service.delete_model(db_session, first.id, second.id)

    remaining = model_service.list_models(db_session)
    assert [m.id for m in remaining] == [second.id]
    assert remaining[0].is_default is True
    assert db_session.get(SecretVaultEntry, secret_ref) is None  # 密钥同事务清理


def test_delete_last_model_clears_everything(
    db_session: Session, secret_key_path: Path,
) -> None:
    only = create(db_session, "A", api_key="sk-only")
    secret_ref = db_session.get(ModelEntry, only.id).secret_ref
    model_service.delete_model(db_session, only.id, None)
    assert model_service.list_models(db_session) == []
    assert db_session.get(SecretVaultEntry, secret_ref) is None
    # 再新增重新自动默认
    reborn = create(db_session, "B")
    assert reborn.is_default is True


# ---- 密钥库（FR-009~012 / SC-002）----


def test_secret_stored_encrypted_not_plaintext(
    db_session: Session, secret_key_path: Path,
) -> None:
    detail = create(db_session, "A", api_key="sk-plaintext-value")
    entry = db_session.get(ModelEntry, detail.id)
    ciphertext = db_session.get(SecretVaultEntry, entry.secret_ref).ciphertext
    assert "sk-plaintext-value" not in ciphertext
    assert secret_vault.load_secret(db_session, entry.secret_ref) == "sk-plaintext-value"


def test_update_keeps_and_replaces_secret(
    db_session: Session, secret_key_path: Path,
) -> None:
    detail = create(db_session, "A", api_key="sk-original")
    # 留空 → 保留
    model_service.update_model(db_session, detail.id, make_request(api_key=None))
    kept_ref = db_session.get(ModelEntry, detail.id).secret_ref
    assert secret_vault.load_secret(db_session, kept_ref) == "sk-original"
    # 填新 → 替换
    model_service.update_model(db_session, detail.id, make_request(api_key="sk-replaced"))
    replaced_ref = db_session.get(ModelEntry, detail.id).secret_ref
    assert secret_vault.load_secret(db_session, replaced_ref) == "sk-replaced"


def test_master_key_file_created(secret_key_path: Path) -> None:
    """主密钥文件在首次存取密钥时自动生成。"""
    assert not secret_key_path.exists()
    secret_vault._load_or_create_fernet()  # noqa: SLF001 — 测试白盒：验证首访生成
    assert secret_key_path.exists()
    assert secret_key_path.stat().st_size > 0


def test_update_does_not_touch_default_flag(db_session: Session) -> None:
    first = create(db_session, "A")
    create(db_session, "B")
    model_service.set_default(db_session, first.id)
    model_service.update_model(db_session, first.id, make_request(display_name="A2"))
    db_session.expire_all()
    assert db_session.get(ModelEntry, first.id).is_default is True

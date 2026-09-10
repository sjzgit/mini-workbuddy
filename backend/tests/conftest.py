"""pytest 共享夹具：测试专用 SQLite 会话、隔离密钥库与 FastAPI TestClient。

003 工具管理新增：内置工具播种夹具（等价迁移播种）与授权目录隔离夹具。
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import secret_vault
from app.core.db import Base, get_session
from app.main import app
from app.models import ToolEntry
from app.services import tool_registry


@pytest.fixture
def secret_key_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """隔离的主密钥文件（不触碰 backend/secret.key），并清空进程内缓存。"""
    key_path = tmp_path / "secret.key"
    monkeypatch.setattr("app.core.secret_vault.settings.secret_vault_path", str(key_path))
    secret_vault.reset_fernet_cache()
    yield key_path
    secret_vault.reset_fernet_cache()


@pytest.fixture
def db_session() -> Iterator[Session]:
    """内存 SQLite 会话（StaticPool 保证同一连接对 TestClient 可见）。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session: Session, secret_key_path: Path) -> Iterator[TestClient]:
    """覆盖 get_session 依赖，应用与路由真实、数据库隔离。"""
    app.dependency_overrides[get_session] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def tools_seeded(db_session: Session) -> Session:
    """播种三条内置工具行（测试库不走 Alembic，等价迁移播种）。"""
    existing = set(db_session.scalars(select(ToolEntry.name)).all())
    for name in tool_registry.builtin_names():
        if name not in existing:
            db_session.add(ToolEntry(name=name, enabled=True))
    db_session.commit()
    return db_session


@pytest.fixture
def workspace_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """隔离的授权目录（不触碰 backend/workspace/），预先创建供测试直接读写。"""
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr("app.core.config.settings.authorized_dir", str(root))
    return root

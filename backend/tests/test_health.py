"""GET /api/health 契约测试。

契约：specs/001-project-init/contracts/api-contract.md
"""

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_session
from app.main import app


def test_health_returns_ok(client: TestClient) -> None:
    """数据库可用时返回 200 与 {"status": "ok"}。"""
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_uses_database_session(db_session: Session) -> None:
    """注入的会话可真实执行 SQL（数据库连接可用）。"""
    result = db_session.execute(text("SELECT 1"))

    assert result.scalar() == 1


def test_health_returns_503_when_database_unavailable() -> None:
    """数据库不可达时返回 503 与 {"status": "unhealthy", "detail": ...}。"""

    def broken_session() -> Iterator[Session]:
        # 指向不存在目录的 SQLite 文件 → 连接必然失败
        broken_engine = create_engine(
            "sqlite:///./__no_such_dir__/broken.db",
            connect_args={"check_same_thread": False},
        )
        broken_factory = sessionmaker(bind=broken_engine)
        session = broken_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = broken_session
    try:
        with TestClient(app) as test_client:
            response = test_client.get("/api/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert "detail" in body


def test_sqlalchemy_error_is_caught_as_unhealthy(client: TestClient) -> None:
    """SELECT 1 抛出 SQLAlchemyError 时走 503 分支（异常不外泄）。"""
    from unittest.mock import patch

    with patch("app.api.health.Session.execute", side_effect=SQLAlchemyError("boom")):
        response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"

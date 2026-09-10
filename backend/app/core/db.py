"""数据库连接与会话管理。

SQLite 是本项目唯一数据库；所有 ORM 模型统一继承 Base。
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """全部 ORM 模型的声明式基类。"""


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI 依赖：提供数据库会话，请求结束自动关闭。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

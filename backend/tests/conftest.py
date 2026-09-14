"""pytest 共享夹具：测试专用 SQLite 会话、隔离密钥库与 FastAPI TestClient。

003 工具管理新增：内置工具播种夹具（等价迁移播种）与授权目录隔离夹具。
"""

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import secret_vault
from app.core.db import Base, get_session
from app.main import app
from app.models import McpServerEntry, ModelEntry, SkillEntry, ToolEntry
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


@pytest.fixture
def skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离的 Skills 目录根（不触碰 backend/workspace/skills/），测试内按需建子目录。"""
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setattr("app.core.config.settings.skills_dir", str(root))
    return root


@pytest.fixture
def mcp_test_timeout(monkeypatch: pytest.MonkeyPatch) -> int:
    """缩短 MCP 测试连接总超时（默认 30s，集成测试压到 3s 控制时长）。"""
    monkeypatch.setattr("app.core.config.settings.mcp_test_timeout_seconds", 3)
    return 3


# ---- 007 Agent 管理共用夹具 ----

@pytest.fixture
def seed_model(db_session: Session) -> ModelEntry:
    """播种一个默认模型（Agent 新建的默认选中项）。"""
    entry = ModelEntry(
        display_name="GPT 测试模型",
        model_identifier="gpt-test",
        base_url="https://api.example.com/v1",
        context_length=8192,
        max_output_tokens=4096,
        temperature=Decimal("0.7"),
        is_default=True,
    )
    db_session.add(entry)
    db_session.commit()
    return entry


@pytest.fixture
def seed_resources(
    db_session: Session, tools_seeded: Session, workspace_dir: Path, skills_dir: Path,
) -> dict:
    """播种工具（内置三条启用）+ Skill（一启用一停用）+ MCP Server（一启用一停用）。

    返回 {"tools": [...], "skills": {...}, "mcps": {...}}，值为主键或行。
    """
    tools = db_session.scalars(select(ToolEntry)).all()

    skill_a_dir = skills_dir / "demo-skill"
    skill_a_dir.mkdir(parents=True)
    (skill_a_dir / "skill.md").write_text(
        "---\nname: 演示技能\ndescription: 用于演示的技能\n---\n\n按步骤执行\n",
        encoding="utf-8",
    )
    skill_a = SkillEntry(dir_name="demo-skill", enabled=True)
    db_session.add(skill_a)

    skill_b_dir = skills_dir / "off-skill"
    skill_b_dir.mkdir(parents=True)
    (skill_b_dir / "skill.md").write_text(
        "---\nname: 停用技能\ndescription: 已停用的技能\n---\n\n不参与候选\n",
        encoding="utf-8",
    )
    skill_b = SkillEntry(dir_name="off-skill", enabled=False)
    db_session.add(skill_b)

    mcp_on = McpServerEntry(
        name="files-mcp", server_type="stdio", command="npx", enabled=True,
    )
    mcp_off = McpServerEntry(
        name="off-mcp", server_type="stdio", command="npx", enabled=False,
    )
    db_session.add_all([mcp_on, mcp_off])
    db_session.commit()

    return {
        "tools": tools,
        "skills": {"on": skill_a, "off": skill_b},
        "mcps": {"on": mcp_on, "off": mcp_off},
    }

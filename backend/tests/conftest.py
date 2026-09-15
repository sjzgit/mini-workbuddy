"""pytest 共享夹具：测试专用 SQLite 会话、隔离密钥库与 FastAPI TestClient。

003 工具管理新增：内置工具播种夹具（等价迁移播种）与授权目录隔离夹具。
"""

from collections.abc import Iterator
import asyncio
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
from app.models import (
    AgentEntry,
    ConversationEntry,
    McpServerEntry,
    ModelEntry,
    SkillEntry,
    ToolEntry,
)
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


# ---- 008 聊天共用夹具 ----


@pytest.fixture
def seed_agent(db_session: Session, seed_model: ModelEntry) -> AgentEntry:
    """播种一个默认 Agent（绑定 seed_model；聊天发送的默认选择）。"""
    entry = AgentEntry(
        name="测试助手",
        description="聊天测试用 Agent",
        model_id=seed_model.id,
        system_prompt="你是一个测试助手。",
        max_rounds=10,
        is_default=True,
    )
    db_session.add(entry)
    db_session.commit()
    return entry


@pytest.fixture
def seed_conversation(db_session: Session, seed_agent: AgentEntry) -> ConversationEntry:
    """播种一个会话（选中 seed_agent）。"""
    entry = ConversationEntry(title="新会话", agent_id=seed_agent.id)
    db_session.add(entry)
    db_session.commit()
    return entry



# ---- 008 聊天：假流注入（specs/008-chat-conversations/research.md R9）----

# 阻塞哨兵：脚本步骤中出现时，生成在 await 点阻塞直至 fake.unblocked = True
# 用字符串而非 object()——conftest 可能被 pytest 与测试文件以不同模块名导入
BLOCK = "__chat_block__"


class FakeStream:
    """可编排的假 stream_chat_completion：记录请求、按脚本产出增量/异常/阻塞。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.steps: list = []
        self.unblocked = True  # 跨线程轮询标志（asyncio.Event 跨线程 set 不安全）

    def script(self, *steps: object) -> None:
        """脚本步骤：delta / Exception / BLOCK（阻塞直至 unblocked=True）。"""
        self.steps = list(steps)

    async def __call__(self, base_url, model_identifier, api_key, messages, **kwargs):
        self.calls.append({"base_url": base_url, "model": model_identifier, "messages": messages, **kwargs})
        for step in self.steps:
            if isinstance(step, Exception):
                raise step
            if step is BLOCK or step == BLOCK:
                self.unblocked = False
                while not self.unblocked:
                    await asyncio.sleep(0.01)
            else:
                yield step


@pytest.fixture
def fake_stream(monkeypatch: pytest.MonkeyPatch) -> FakeStream:
    """替换 chat_service.stream_chat_completion 引用为假流。"""
    from app.services import chat_service

    fake = FakeStream()
    monkeypatch.setattr(chat_service, "stream_chat_completion", fake)
    return fake


@pytest.fixture
def clean_registry():
    """测试前后清空生成注册表（避免用例间串扰）。"""
    from app.services.generation_registry import get_registry

    get_registry()._tasks.clear()
    yield
    get_registry()._tasks.clear()


@pytest.fixture
def chat_session_factory(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> sessionmaker:
    """把 chat_service.SessionLocal 指向测试库（生成任务收尾用独立会话落库）。"""
    from app.services import chat_service

    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(chat_service, "SessionLocal", factory)
    return factory

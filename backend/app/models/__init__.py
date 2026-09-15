"""ORM 模型层。

数据模型主定义：specs/002-model-management/data-model.md、specs/003-tool-management/data-model.md
本文件字段与类型 MUST 与主定义一致，变更先改主定义再落 Alembic 迁移。
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _utcnow() -> datetime:
    """SQLite DateTime 不带时区，统一存 naive UTC。"""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


class SecretVaultEntry(Base):
    """secrets_vault 表：密钥密文（只有 core.secret_vault 一个访问入口）。"""

    __tablename__ = "secrets_vault"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ciphertext: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow,
    )


class ModelEntry(Base):
    """models 表：模型接入配置（不含任何密钥材料，仅存 secret_ref 指针）。"""

    __tablename__ = "models"

    __table_args__ = (
        # 部分唯一索引：数据库层保证至多一个默认模型（research R2）
        Index(
            "uq_models_single_default",
            "is_default",
            unique=True,
            sqlite_where=text("is_default = 1"),
        ),
        Index("ix_models_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_identifier: Mapped[str] = mapped_column(String(200), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    secret_ref: Mapped[int | None] = mapped_column(
        ForeignKey("secrets_vault.id"), nullable=True,
    )
    context_length: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    temperature: Mapped[Decimal] = mapped_column(Numeric(3, 1), nullable=False)
    input_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    output_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    cached_input_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow,
    )


class ToolEntry(Base):
    """tools 表：工具注册事实与启停状态。

    数据模型主定义：specs/003-tool-management/data-model.md
    元数据（名称/说明/参数）不入库，由 services/tool_registry.py 承载；
    name 合法取值 = 注册表键（current_time / shell / file_read_write）。
    """

    __tablename__ = "tools"

    __table_args__ = (
        Index("uq_tools_name", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow,
    )


class SkillEntry(Base):
    """skills 表：Skill 目录的启用状态（内容以 workspace/skills/ 文件为本体，不入库）。

    数据模型主定义：specs/004-skills-mcp-management/data-model.md
    dir_name 合法取值 = workspace/skills/ 下合规目录集合；刷新动作做"目录 ↔ 行"同步。
    """

    __tablename__ = "skills"

    __table_args__ = (
        Index("uq_skills_dir_name", "dir_name", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dir_name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow,
    )


class McpServerEntry(Base):
    """mcp_servers 表：MCP Server 配置、启用状态与最近一次测试快照。

    数据模型主定义：specs/004-skills-mcp-management/data-model.md
    敏感值（env/headers）不入本表——密文存 secrets_vault，本表只持指针；
    tools_json 是工具列表快照（整体覆写，不建第三张表，research R6）。
    """

    __tablename__ = "mcp_servers"

    __table_args__ = (
        Index("uq_mcp_servers_name", "name", unique=True),
        Index("ix_mcp_servers_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=text("''"),
    )
    server_type: Mapped[str] = mapped_column(String(10), nullable=False)  # stdio | http
    command: Mapped[str | None] = mapped_column(String(500), nullable=True)
    command_args: Mapped[list | None] = mapped_column(JSON, nullable=True)
    env_secret_ref: Mapped[int | None] = mapped_column(
        ForeignKey("secrets_vault.id"), nullable=True,
    )
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    headers_secret_ref: Mapped[int | None] = mapped_column(
        ForeignKey("secrets_vault.id"), nullable=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1"),
    )
    last_test_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    last_test_tool_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tools_json: Mapped[str | None] = mapped_column(String(100000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow,
    )


class AgentEntry(Base):
    """agents 表：Agent 主配置。

    数据模型主定义：specs/007-agent-management/data-model.md §1
    model_id 为业务引用（不建 DB 外键，资源删除保护走应用层，research R4）；
    system_prompt 是版本表最新行的冗余快照（直读免 join，research R1/R5）。
    """

    __tablename__ = "agents"

    __table_args__ = (
        # 部分唯一索引：数据库层保证至多一个默认 Agent（research R2）
        Index(
            "uq_agents_single_default",
            "is_default",
            unique=True,
            sqlite_where=text("is_default = 1"),
        ),
        Index("ix_agents_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=text("''"),
    )
    model_id: Mapped[int] = mapped_column(Integer, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    max_rounds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default=text("10"),
    )
    enable_deep_thinking: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0"),
    )
    thinking_level: Mapped[str] = mapped_column(
        String(10), nullable=False, default="off", server_default=text("'off'"),
    )  # off | low | medium | high（contracts ThinkingLevel）
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow,
    )


class ConversationEntry(Base):
    """conversations 表：会话（聊天功能第八阶段）。

    数据模型主定义：specs/008-chat-conversations/data-model.md §1
    agent_id 为业务引用（不建 DB 外键）——Agent 删除不阻断会话查看，
    发送前由应用层校验可用性（spec 切换 Agent 节）。
    """

    __tablename__ = "conversations"

    __table_args__ = (
        Index("ix_conversations_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(
        String(100), nullable=False, default="新会话", server_default=text("'新会话'"),
    )
    agent_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow,
    )


class MessageEntry(Base):
    """messages 表：聊天消息（用户消息 / Agent 回复）。

    数据模型主定义：specs/008-chat-conversations/data-model.md §2
    seq 是会话内唯一顺序号（读取排序唯一依据，禁止仅按时间戳排序）；
    assistant 回复生成期间先落 generating 占位行，终态单次 UPDATE；
    agent_id / agent_name 是生成时刻快照，不随 Agent 后续变化。
    """

    __tablename__ = "messages"

    __table_args__ = (
        Index("uq_messages_conversation_seq", "conversation_id", "seq", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False,
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # user | assistant
    agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reasoning_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="completed",
    )  # generating | completed | incomplete（contracts MessageStatus）
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )


class AgentBinding(Base):
    """agent_bindings 表：Agent 与工具 / Skill / MCP Server 的绑定（通表）。

    数据模型主定义：specs/007-agent-management/data-model.md §2
    (resource_type, resource_id) 不建 DB 外键——删除保护在应用层（research R4）；
    agent_id 外键 ON DELETE CASCADE 兜底（SQLite 需 PRAGMA 生效，service 层显式清理为准）。
    """

    __tablename__ = "agent_bindings"

    __table_args__ = (
        Index(
            "uq_agent_bindings_unique",
            "agent_id", "resource_type", "resource_id",
            unique=True,
        ),
        # 反查"哪些 Agent 引用了此资源"——删除保护高频查询（research R4）
        Index("ix_agent_bindings_resource", "resource_type", "resource_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False,
    )
    resource_type: Mapped[str] = mapped_column(String(10), nullable=False)  # tool | skill | mcp
    resource_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )


class AgentPromptVersion(Base):
    """agent_prompt_versions 表：系统提示词版本快照（只追加，历史只读）。

    数据模型主定义：specs/007-agent-management/data-model.md §3
    仅当提示词内容变化时追加（FR-018~020），任何业务路径不 UPDATE/DELETE 此表。
    """

    __tablename__ = "agent_prompt_versions"

    __table_args__ = (
        Index(
            "uq_agent_prompt_versions",
            "agent_id", "version",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )

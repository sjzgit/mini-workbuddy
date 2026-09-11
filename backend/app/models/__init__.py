"""ORM 模型层。

数据模型主定义：specs/002-model-management/data-model.md、specs/003-tool-management/data-model.md
本文件字段与类型 MUST 与主定义一致，变更先改主定义再落 Alembic 迁移。
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, text
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

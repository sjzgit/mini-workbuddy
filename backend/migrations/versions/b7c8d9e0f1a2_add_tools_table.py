"""add tools table with builtin seed rows

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-09-10

数据模型主定义：specs/003-tool-management/data-model.md
"""

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 播种行（注册表键，契约主定义 specs/003-tool-management/contracts/tool-definitions.md §1）
_SEED_TOOL_NAMES = ("current_time", "file_read_write", "shell")


def upgrade() -> None:
    tools = op.create_table(
        "tools",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_tools_name", "tools", ["name"], unique=True)
    # 建表即播种三条内置工具（默认启用）；新建表无既有行，无需幂等判断
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    op.bulk_insert(
        tools,
        [
            {"name": name, "enabled": True, "created_at": now, "updated_at": now}
            for name in _SEED_TOOL_NAMES
        ],
    )


def downgrade() -> None:
    op.drop_index("uq_tools_name", table_name="tools")
    op.drop_table("tools")

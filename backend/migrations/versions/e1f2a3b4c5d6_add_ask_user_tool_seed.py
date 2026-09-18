"""add ask_user tool seed

Revision ID: e1f2a3b4c5d6
Revises: de50fb3128d4
Create Date: 2026-09-18

数据模型主定义：specs/013-ask-user-tool/data-model.md §1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "de50fb3128d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """幂等补种 ask_user 内置工具行（默认启用）。"""
    op.execute(
        "INSERT INTO tools (name, enabled, created_at, updated_at) "
        "SELECT 'ask_user', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
        "WHERE NOT EXISTS (SELECT 1 FROM tools WHERE name = 'ask_user')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM tools WHERE name = 'ask_user'")

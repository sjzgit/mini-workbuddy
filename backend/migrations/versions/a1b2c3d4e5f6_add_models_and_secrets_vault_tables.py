"""add models and secrets_vault tables

Revision ID: a1b2c3d4e5f6
Revises: e39fd44e62e2
Create Date: 2026-09-10

数据模型主定义：specs/002-model-management/data-model.md
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "e39fd44e62e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "secrets_vault",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ciphertext", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "models",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("model_identifier", sa.String(length=200), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("secret_ref", sa.Integer(), nullable=True),
        sa.Column("context_length", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("temperature", sa.Numeric(3, 1), nullable=False),
        sa.Column("input_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("output_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("cached_input_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["secret_ref"], ["secrets_vault.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # 部分唯一索引：数据库层保证至多一个默认模型（research R2）
    op.create_index("ix_models_updated_at", "models", ["updated_at"], unique=False)
    op.execute(
        "CREATE UNIQUE INDEX uq_models_single_default ON models (is_default) WHERE is_default = 1",
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_models_single_default")
    op.drop_index("ix_models_updated_at", table_name="models")
    op.drop_table("models")
    op.drop_table("secrets_vault")

"""add agents, agent_bindings, agent_prompt_versions tables

Revision ID: d4e5f6a7b8c9
Revises: 0ec5128a2206
Create Date: 2026-09-11

数据模型主定义：specs/007-agent-management/data-model.md §1–§3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = '0ec5128a2206'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'agents',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), server_default=sa.text("('')"), nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=False),
        sa.Column('system_prompt', sa.Text(), nullable=False),
        sa.Column('max_rounds', sa.Integer(), server_default=sa.text('10'), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.create_index(
            'uq_agents_single_default', ['is_default'],
            unique=True, sqlite_where=sa.text('is_default = 1'),
        )
        batch_op.create_index('ix_agents_updated_at', ['updated_at'], unique=False)

    op.create_table(
        'agent_bindings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=False),
        sa.Column('resource_type', sa.String(length=10), nullable=False),
        sa.Column('resource_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    )
    with op.batch_alter_table('agent_bindings', schema=None) as batch_op:
        batch_op.create_index(
            'uq_agent_bindings_unique',
            ['agent_id', 'resource_type', 'resource_id'], unique=True,
        )
        batch_op.create_index(
            'ix_agent_bindings_resource', ['resource_type', 'resource_id'], unique=False,
        )

    op.create_table(
        'agent_prompt_versions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    )
    with op.batch_alter_table('agent_prompt_versions', schema=None) as batch_op:
        batch_op.create_index(
            'uq_agent_prompt_versions', ['agent_id', 'version'], unique=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('agent_prompt_versions', schema=None) as batch_op:
        batch_op.drop_index('uq_agent_prompt_versions')
    op.drop_table('agent_prompt_versions')
    with op.batch_alter_table('agent_bindings', schema=None) as batch_op:
        batch_op.drop_index('ix_agent_bindings_resource')
        batch_op.drop_index('uq_agent_bindings_unique')
    op.drop_table('agent_bindings')
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.drop_index('ix_agents_updated_at')
        batch_op.drop_index('uq_agents_single_default')
    op.drop_table('agents')

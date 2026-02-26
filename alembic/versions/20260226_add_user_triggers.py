"""add_user_triggers

Revision ID: 20260226_add_user_triggers
Revises: 20260128_add_vector_indexes
Create Date: 2026-02-26 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '20260226_add_user_triggers'
down_revision: Union[str, Sequence[str], None] = '20260128_add_vector_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_triggers',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('cron_hour', sa.Integer(), nullable=False),
        sa.Column('cron_minute', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cron_weekdays', sa.String(length=50), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_user_triggers_user_id', 'user_triggers', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_user_triggers_user_id', table_name='user_triggers')
    op.drop_table('user_triggers')

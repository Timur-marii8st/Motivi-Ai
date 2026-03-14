"""add_integrity_sig_columns

Revision ID: 20260304_add_integrity_sig_columns
Revises: 20260301_add_userbot_session_and_settings
Create Date: 2026-03-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260304_add_integrity_sig_columns"
down_revision: Union[str, Sequence[str], None] = "20260301_add_userbot_session_and_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("integrity_sig", sa.String(length=64), nullable=True))
    op.add_column("core_memory", sa.Column("integrity_sig", sa.String(length=64), nullable=True))
    op.add_column("working_memory", sa.Column("integrity_sig", sa.String(length=64), nullable=True))
    op.add_column("working_memory_entry", sa.Column("integrity_sig", sa.String(length=64), nullable=True))
    op.add_column("episodes", sa.Column("integrity_sig", sa.String(length=64), nullable=True))
    op.add_column("user_settings", sa.Column("integrity_sig", sa.String(length=64), nullable=True))
    op.add_column("habits", sa.Column("integrity_sig", sa.String(length=64), nullable=True))
    op.add_column("plans", sa.Column("integrity_sig", sa.String(length=64), nullable=True))
    op.add_column("userbot_sessions", sa.Column("integrity_sig", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("userbot_sessions", "integrity_sig")
    op.drop_column("plans", "integrity_sig")
    op.drop_column("habits", "integrity_sig")
    op.drop_column("user_settings", "integrity_sig")
    op.drop_column("episodes", "integrity_sig")
    op.drop_column("working_memory_entry", "integrity_sig")
    op.drop_column("working_memory", "integrity_sig")
    op.drop_column("core_memory", "integrity_sig")
    op.drop_column("users", "integrity_sig")

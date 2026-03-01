"""add_userbot_session_and_settings

Creates the userbot_sessions table and adds userbot-related columns to
user_settings: enable_channel_monitoring, enable_dm_notifications,
userbot_channel_interests.

Revision ID: 20260301_add_userbot_session_and_settings
Revises: 20260228_add_search_news_digest_settings
Create Date: 2026-03-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260301_add_userbot_session_and_settings"
down_revision: Union[str, Sequence[str], None] = "20260228_add_search_news_digest_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── New table: userbot_sessions ────────────────────────────────────────
    op.create_table(
        "userbot_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        # Encrypted Telethon StringSession; stored as TEXT, encrypted at app level
        sa.Column("session_string", sa.Text(), nullable=True),
        # Encrypted E.164 phone number
        sa.Column("phone_number", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_userbot_sessions_user"),
    )
    op.create_index("ix_userbot_sessions_user_id", "userbot_sessions", ["user_id"])

    # ── New columns: user_settings ─────────────────────────────────────────
    op.add_column(
        "user_settings",
        sa.Column(
            "enable_channel_monitoring",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "user_settings",
        sa.Column(
            "enable_dm_notifications",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "user_settings",
        sa.Column("userbot_channel_interests", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "userbot_channel_interests")
    op.drop_column("user_settings", "enable_dm_notifications")
    op.drop_column("user_settings", "enable_channel_monitoring")
    op.drop_index("ix_userbot_sessions_user_id", table_name="userbot_sessions")
    op.drop_table("userbot_sessions")

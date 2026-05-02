"""add userbot threads

Revision ID: 20260502_add_userbot_threads
Revises: 20260501_add_smart_proactivity_settings
Create Date: 2026-05-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260502_add_userbot_threads"
down_revision: Union[str, Sequence[str], None] = (
    "20260501_add_smart_proactivity_settings"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "userbot_threads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "chat_type", sa.String(length=20), nullable=False, server_default="dm"
        ),
        sa.Column("sender_tg_id", sa.BigInteger(), nullable=True),
        sa.Column("sender_name", sa.String(length=255), nullable=True),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("message_text", sa.Text(), nullable=True),
        sa.Column("message_summary", sa.Text(), nullable=True),
        sa.Column("suggested_replies_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="new"),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="3"),
        sa.Column(
            "requires_response",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "memory_worthy",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("memory_items_json", sa.Text(), nullable=True),
        sa.Column("response_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_incoming_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outgoing_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index("ix_userbot_threads_user_id", "userbot_threads", ["user_id"])
    op.create_index("ix_userbot_threads_chat_id", "userbot_threads", ["chat_id"])
    op.create_index("ix_userbot_threads_chat_type", "userbot_threads", ["chat_type"])
    op.create_index(
        "ix_userbot_threads_sender_tg_id", "userbot_threads", ["sender_tg_id"]
    )
    op.create_index("ix_userbot_threads_message_id", "userbot_threads", ["message_id"])
    op.create_index("ix_userbot_threads_status", "userbot_threads", ["status"])
    op.create_index("ix_userbot_threads_importance", "userbot_threads", ["importance"])
    op.create_index(
        "ix_userbot_threads_response_deadline_at",
        "userbot_threads",
        ["response_deadline_at"],
    )
    op.create_index(
        "ix_userbot_threads_last_incoming_at", "userbot_threads", ["last_incoming_at"]
    )

    op.add_column(
        "user_settings",
        sa.Column(
            "enable_userbot_followups",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "user_settings",
        sa.Column(
            "enable_userbot_memory_ingest",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "user_settings",
        sa.Column(
            "userbot_followup_max_per_day",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("5"),
        ),
    )
    op.add_column(
        "user_settings",
        sa.Column(
            "userbot_memory_privacy_level",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'conservative'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "userbot_memory_privacy_level")
    op.drop_column("user_settings", "userbot_followup_max_per_day")
    op.drop_column("user_settings", "enable_userbot_memory_ingest")
    op.drop_column("user_settings", "enable_userbot_followups")

    op.drop_index("ix_userbot_threads_last_incoming_at", table_name="userbot_threads")
    op.drop_index(
        "ix_userbot_threads_response_deadline_at", table_name="userbot_threads"
    )
    op.drop_index("ix_userbot_threads_importance", table_name="userbot_threads")
    op.drop_index("ix_userbot_threads_status", table_name="userbot_threads")
    op.drop_index("ix_userbot_threads_message_id", table_name="userbot_threads")
    op.drop_index("ix_userbot_threads_sender_tg_id", table_name="userbot_threads")
    op.drop_index("ix_userbot_threads_chat_type", table_name="userbot_threads")
    op.drop_index("ix_userbot_threads_chat_id", table_name="userbot_threads")
    op.drop_index("ix_userbot_threads_user_id", table_name="userbot_threads")
    op.drop_table("userbot_threads")

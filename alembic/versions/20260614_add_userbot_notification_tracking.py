"""add userbot notification tracking

Revision ID: 20260614_add_userbot_notification_tracking
Revises: 20260507_add_private_topic_id_to_users
Create Date: 2026-06-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260614_add_userbot_notification_tracking"
down_revision: Union[str, Sequence[str], None] = (
    "20260507_add_private_topic_id_to_users"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "userbot_threads",
        sa.Column("notification_chat_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "userbot_threads",
        sa.Column("notification_message_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "userbot_threads",
        sa.Column("notification_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "userbot_threads",
        sa.Column("pending_key", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_userbot_threads_pending_key",
        "userbot_threads",
        ["pending_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_userbot_threads_pending_key", table_name="userbot_threads")
    op.drop_column("userbot_threads", "pending_key")
    op.drop_column("userbot_threads", "notification_sent_at")
    op.drop_column("userbot_threads", "notification_message_id")
    op.drop_column("userbot_threads", "notification_chat_id")

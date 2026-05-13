"""add private topic id to users

Revision ID: 20260507_add_private_topic_id_to_users
Revises: 20260502_add_userbot_threads
Create Date: 2026-05-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260507_add_private_topic_id_to_users"
down_revision: Union[str, Sequence[str], None] = "20260502_add_userbot_threads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("tg_private_topic_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "tg_private_topic_id")

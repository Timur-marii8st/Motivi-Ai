"""add_userbot_reply_approval

Adds group monitoring and reply approval columns to user_settings.

Revision ID: 20260314_add_userbot_reply_approval
Revises: 2213045bad38
Create Date: 2026-03-14 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260314_add_userbot_reply_approval"
down_revision: Union[str, Sequence[str], None] = "2213045bad38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "enable_group_monitoring",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "user_settings",
        sa.Column(
            "enable_reply_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "enable_reply_approval")
    op.drop_column("user_settings", "enable_group_monitoring")

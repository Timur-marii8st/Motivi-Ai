"""add smart proactivity settings

Revision ID: 20260501_add_smart_proactivity_settings
Revises: 20260427_add_payments_table
Create Date: 2026-05-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260501_add_smart_proactivity_settings"
down_revision: Union[str, Sequence[str], None] = "20260427_add_payments_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "enable_smart_proactivity",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "user_settings",
        sa.Column(
            "proactive_max_messages_per_day",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "proactive_max_messages_per_day")
    op.drop_column("user_settings", "enable_smart_proactivity")

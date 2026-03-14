"""add_bot_persona_to_user_settings

Adds bot_persona column to user_settings table.
Allows users to choose their preferred bot communication style
(strict, friendly, coach, zen, hype). Defaults to "strict" to
preserve existing behaviour.

Revision ID: 20260314_add_bot_persona
Revises: 20260310_add_gamification_system
Create Date: 2026-03-14 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260314_add_bot_persona"
down_revision: Union[str, Sequence[str], None] = "20260310_add_gamification_system"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "bot_persona",
            sa.String(30),
            nullable=False,
            server_default="strict",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "bot_persona")

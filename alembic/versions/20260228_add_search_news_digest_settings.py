"""add_search_news_digest_settings

Adds enable_news_digest column to user_settings table.

Revision ID: 20260228_add_search_news_digest_settings
Revises: 20260226_add_user_triggers
Create Date: 2026-02-28 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20260228_add_search_news_digest_settings"
down_revision: Union[str, Sequence[str], None] = "20260226_add_user_triggers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "enable_news_digest",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "enable_news_digest")

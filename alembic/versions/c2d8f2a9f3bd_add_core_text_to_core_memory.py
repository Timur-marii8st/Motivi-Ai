"""add core_text to core_memory

Revision ID: c2d8f2a9f3bd
Revises: b7c9e1d4f1a2
Create Date: 2025-10-25 14:23:00.000000

"""
from alembic import op
import sqlalchemy as sa
from typing import Union, Sequence

# revision identifiers, used by Alembic.
revision: str = "c2d8f2a9f3bd"
down_revision: Union[str, Sequence[str], None] = "b7c9e1d4f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add core_text column to core_memory (nullable, text)
    op.add_column("core_memory", sa.Column("core_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("core_memory", "core_text")

"""Merge heads

Revision ID: 51d1ea426c9b
Revises: 20251204_add_core_fact_table, 8edfc37203e1
Create Date: 2025-12-04 18:57:38.717253

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '51d1ea426c9b'
down_revision: Union[str, Sequence[str], None] = ('20251204_add_core_fact_table', '8edfc37203e1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

"""Объединение параллельных веток миграций

Revision ID: d807fd565f4a
Revises: 446b10e61ce0, add_working_memory_entries
Create Date: 2025-11-03 15:54:47.096593

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd807fd565f4a'
down_revision: Union[str, Sequence[str], None] = ('446b10e61ce0', 'add_working_memory_entries')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

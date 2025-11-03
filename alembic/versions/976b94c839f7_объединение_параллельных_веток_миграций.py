"""Объединение параллельных веток миграций

Revision ID: 976b94c839f7
Revises: 4e25668ea81e, fix_core_memory_timezone
Create Date: 2025-11-02 19:28:20.444971

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '976b94c839f7'
down_revision: Union[str, Sequence[str], None] = ('4e25668ea81e', 'fix_core_memory_timezone')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

"""Merge multiple heads

Revision ID: 6c229648795b
Revises: e5f5d8c7e6b4, f6f6e8d8d7e5
Create Date: 2025-10-31 11:02:38.199336

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6c229648795b'
down_revision: Union[str, Sequence[str], None] = ('e5f5d8c7e6b4', 'f6f6e8d8d7e5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

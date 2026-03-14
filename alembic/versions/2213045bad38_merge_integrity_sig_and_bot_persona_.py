"""merge integrity_sig and bot_persona heads

Revision ID: 2213045bad38
Revises: 20260304_add_integrity_sig_columns, 20260314_add_bot_persona
Create Date: 2026-03-14 14:09:19.899273

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2213045bad38'
down_revision: Union[str, Sequence[str], None] = ('20260304_add_integrity_sig_columns', '20260314_add_bot_persona')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

"""rename timezone to user timezone

Revision ID: e5f5d8c7e6b4
Revises: d4a4c7e6b2f1
Create Date: 2025-10-27 21:45:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e5f5d8c7e6b4'
down_revision: Union[str, None] = 'd4a4c7e6b2f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename column timezone to user_timezone
    op.alter_column('users', 'timezone', new_column_name='user_timezone')


def downgrade() -> None:
    # Rename column user_timezone back to timezone
    op.alter_column('users', 'user_timezone', new_column_name='timezone')
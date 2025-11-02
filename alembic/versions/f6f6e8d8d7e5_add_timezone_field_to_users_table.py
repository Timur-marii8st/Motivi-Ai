"""add timezone field to users table

Revision ID: f6f6e8d8d7e5
Revises: d4a4c7e6b2f1
Create Date: 2025-10-27 22:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f6f6e8d8d7e5'
down_revision: Union[str, None] = 'd4a4c7e6b2f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # First add the user_timezone column
    op.add_column('users', sa.Column('user_timezone', sa.String(), nullable=True))


def downgrade() -> None:
    # Remove the user_timezone column
    op.drop_column('users', 'user_timezone')
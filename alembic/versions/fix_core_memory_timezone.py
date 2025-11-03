"""Fix core_memory updated_at timezone awareness

Revision ID: fix_core_memory_timezone
Revises: e5f5d8c7e6b4
Create Date: 2025-11-02 21:57:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'fix_core_memory_timezone'
down_revision: str = 'e5f5d8c7e6b4'
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Upgrade core_memory.updated_at to use timezone."""
    op.alter_column('core_memory', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               type_=sa.DateTime(timezone=True),
               existing_nullable=False)


def downgrade() -> None:
    """Downgrade core_memory.updated_at to not use timezone."""
    op.alter_column('core_memory', 'updated_at',
               existing_type=sa.DateTime(timezone=True),
               type_=postgresql.TIMESTAMP(),
               existing_nullable=False)
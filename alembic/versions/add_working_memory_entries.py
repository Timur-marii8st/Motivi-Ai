"""create working_memory_entry tables

Revision ID: add_working_memory_entries
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_working_memory_entries'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'working_memory_entry',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('working_memory_text', sa.Text(), nullable=True),
        sa.Column('history_order', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False),
    )

    op.create_index('ix_working_memory_entry_user_history', 'working_memory_entry', ['user_id', 'history_order'])

    op.create_table(
        'working_memory_entry_embeddings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('working_entry_id', sa.Integer(), nullable=False),
        sa.Column('embedding', sa.dialects.postgresql.ARRAY(sa.Float)),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('working_memory_entry_embeddings')
    op.drop_index('ix_working_memory_entry_user_history')
    op.drop_table('working_memory_entry')

"""
add_core_fact_table

Revision ID: 20251204_add_core_fact_table
Revises: 
Create Date: 2025-12-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251204_add_core_fact_table'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'core_facts',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('core_memory_id', sa.Integer, sa.ForeignKey('core_memory.id'), nullable=False),
        sa.Column('fact_text', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'core_fact_embeddings',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('core_fact_id', sa.Integer, sa.ForeignKey('core_facts.id'), nullable=False, unique=True),
        sa.Column('embedding', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('core_fact_embeddings')
    op.drop_table('core_facts')

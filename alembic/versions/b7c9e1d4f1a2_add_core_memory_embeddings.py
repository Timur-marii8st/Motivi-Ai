"""add core_memory_embeddings table

Revision ID: b7c9e1d4f1a2
Revises: a3bfc1bad709
Create Date: 2025-10-25 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from typing import Union, Sequence

# revision identifiers, used by Alembic.
revision: str = "b7c9e1d4f1a2"
down_revision: Union[str, Sequence[str], None] = "a3bfc1bad709"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure pgvector extension is present
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Create the table using raw SQL so we can use the 'vector' column type
    # directly; this ensures pgvector operators (like <=>) work as expected.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS core_memory_embeddings (
            id SERIAL PRIMARY KEY,
            core_memory_id INTEGER NOT NULL UNIQUE REFERENCES core_memory(id),
            embedding VECTOR(1536) NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS core_memory_embeddings;")

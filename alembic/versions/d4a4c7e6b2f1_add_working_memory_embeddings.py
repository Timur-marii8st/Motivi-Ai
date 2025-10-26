"""add working_memory_embeddings table

Revision ID: d4a4c7e6b2f1
Revises: c2d8f2a9f3bd
Create Date: 2025-10-25 14:40:00.000000

"""
from alembic import op
import sqlalchemy as sa
from typing import Union, Sequence

# revision identifiers, used by Alembic.
revision: str = "d4a4c7e6b2f1"
down_revision: Union[str, Sequence[str], None] = "c2d8f2a9f3bd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure pgvector extension is present
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Create the working_memory_embeddings table using raw SQL so the VECTOR
    # type is created as pgvector's vector(1536).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS working_memory_embeddings (
            id SERIAL PRIMARY KEY,
            working_memory_id INTEGER NOT NULL UNIQUE REFERENCES working_memory(id),
            embedding VECTOR(1536) NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS working_memory_embeddings;")

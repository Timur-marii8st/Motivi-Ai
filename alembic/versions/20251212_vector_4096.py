"""
update_vector_dimensions_to_4096

Revision ID: 20251212_vector_4096
Revises: fc08a8eb9107
Create Date: 2025-12-12 00:00:00.000000

Updates vector column dimensions from 1536 (Gemini/OpenAI) to 4096 (Qwen embeddings)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20251212_vector_4096'
down_revision = 'fc08a8eb9107'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Update episode_embeddings.embedding from vector(1536) to vector(4096)
    op.execute('ALTER TABLE episode_embeddings ALTER COLUMN embedding TYPE vector(4096) USING embedding::vector(4096)')

    # Update core_memory_embeddings.embedding from vector(1536) to vector(4096)
    op.execute('ALTER TABLE core_memory_embeddings ALTER COLUMN embedding TYPE vector(4096) USING embedding::vector(4096)')

    # Update core_fact_embeddings.embedding from vector(1536) to vector(4096)
    op.execute('ALTER TABLE core_fact_embeddings ALTER COLUMN embedding TYPE vector(4096) USING embedding::vector(4096)')

    # Update working_memory_entry_embeddings.embedding from vector(1536) to vector(4096)
    op.execute('ALTER TABLE working_memory_entry_embeddings ALTER COLUMN embedding TYPE vector(4096) USING embedding::vector(4096)')

    # Update working_memory_embeddings.embedding from vector(1536) to vector(4096)
    op.execute('ALTER TABLE working_memory_embeddings ALTER COLUMN embedding TYPE vector(4096) USING embedding::vector(4096)')


def downgrade() -> None:
    # Revert vector dimensions back to 1536 if needed
    op.execute('ALTER TABLE episode_embeddings ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)')
    op.execute('ALTER TABLE core_memory_embeddings ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)')
    op.execute('ALTER TABLE core_fact_embeddings ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)')
    op.execute('ALTER TABLE working_memory_entry_embeddings ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)')
    op.execute('ALTER TABLE working_memory_embeddings ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)')

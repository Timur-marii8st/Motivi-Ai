"""
add_vector_indexes

Revision ID: 20260128_add_vector_indexes
Revises: 20251212_vector_4096
Create Date: 2026-01-28 18:23:35.000000

Adds IVFFlat indexes for all vector columns to optimize similarity search performance.
Without these indexes, vector similarity queries perform full table scans.

Note: Using IVFFlat instead of HNSW because our vectors are 4096-dimensional.
HNSW has a limit of 2000 dimensions in pgvector.
IVFFlat is better suited for high-dimensional vectors (>2000 dimensions).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '20260128_add_vector_indexes'
down_revision = '20251212_vector_4096'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create IVFFlat indexes for all vector columns
    # IVFFlat (Inverted File with Flat compression) is optimal for high-dimensional vectors (>2000 dims)
    # HNSW has a 2000 dimension limit, so we use IVFFlat for 4096-dimensional vectors
    # lists parameter: sqrt(total_rows) is a good starting point, we use 100 as default
    # This can be tuned later based on actual data size
    
    # Episode embeddings
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_episode_embeddings_ivfflat 
        ON episode_embeddings 
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)
    
    # Core memory embeddings
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_core_memory_embeddings_ivfflat 
        ON core_memory_embeddings 
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)
    
    # Core fact embeddings
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_core_fact_embeddings_ivfflat 
        ON core_fact_embeddings 
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)
    
    # Working memory entry embeddings
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_working_memory_entry_embeddings_ivfflat 
        ON working_memory_entry_embeddings 
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)
    
    # Working memory embeddings
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_working_memory_embeddings_ivfflat 
        ON working_memory_embeddings 
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)


def downgrade() -> None:
    # Drop all IVFFlat indexes
    op.execute("DROP INDEX IF EXISTS idx_episode_embeddings_ivfflat")
    op.execute("DROP INDEX IF EXISTS idx_core_memory_embeddings_ivfflat")
    op.execute("DROP INDEX IF EXISTS idx_core_fact_embeddings_ivfflat")
    op.execute("DROP INDEX IF EXISTS idx_working_memory_entry_embeddings_ivfflat")
    op.execute("DROP INDEX IF EXISTS idx_working_memory_embeddings_ivfflat")

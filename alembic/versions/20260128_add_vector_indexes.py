"""
add_vector_indexes

Revision ID: 20260128_add_vector_indexes
Revises: 20251212_vector_4096
Create Date: 2026-01-28 18:23:35.000000

Adds HNSW indexes for all vector columns to optimize similarity search performance.
Without these indexes, vector similarity queries perform full table scans.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '20260128_add_vector_indexes'
down_revision = '20251212_vector_4096'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create HNSW indexes for all vector columns
    # HNSW (Hierarchical Navigable Small World) is optimal for high-dimensional vectors
    # vector_cosine_ops is the operator class for cosine similarity
    
    # Episode embeddings
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_episode_embeddings_hnsw 
        ON episode_embeddings 
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    
    # Core memory embeddings
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_core_memory_embeddings_hnsw 
        ON core_memory_embeddings 
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    
    # Core fact embeddings
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_core_fact_embeddings_hnsw 
        ON core_fact_embeddings 
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    
    # Working memory entry embeddings
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_working_memory_entry_embeddings_hnsw 
        ON working_memory_entry_embeddings 
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    
    # Working memory embeddings
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_working_memory_embeddings_hnsw 
        ON working_memory_embeddings 
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    # Drop all HNSW indexes
    op.execute("DROP INDEX IF EXISTS idx_episode_embeddings_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_core_memory_embeddings_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_core_fact_embeddings_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_working_memory_entry_embeddings_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_working_memory_embeddings_hnsw")

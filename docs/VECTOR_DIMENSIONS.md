# Vector Dimensions Configuration

## Overview

This project uses pgvector for storing and searching embeddings. The vector dimension must match the output of the embedding model.

## Current Configuration

- **Model**: `qwen/qwen3-embedding-8b` (via OpenRouter)
- **Dimension**: 4096
- **Config Variable**: `settings.VECTOR_DIM` in `app/config.py`

## Important Notes

### Changing Embedding Models

If you change the embedding model (`EMBEDDING_MODEL_ID`), you MUST:

1. **Verify the model's output dimension**
   - Check the model documentation
   - Test with a sample embedding call
   - Common dimensions: 384, 768, 1024, 1536, 3072, 4096

2. **Update the configuration**
   ```python
   # In app/config.py
   VECTOR_DIM: int = <new_dimension>
   ```

3. **Create a migration to update database columns**
   ```python
   # Example migration
   op.execute('ALTER TABLE episode_embeddings ALTER COLUMN embedding TYPE vector(<new_dim>) USING embedding::vector(<new_dim>)')
   ```

4. **Rebuild all existing embeddings**
   - Old embeddings with different dimensions will cause errors
   - You'll need to re-generate all embeddings with the new model

### Validation

The embedding client should validate dimensions on initialization:

```python
# In app/embeddings/gemini_embedding_client.py
def __init__(self):
    # Test embedding to verify dimension
    test_vec = self.embed("test")
    if len(test_vec) != settings.VECTOR_DIM:
        raise ValueError(
            f"Model returns {len(test_vec)}-dim vectors, "
            f"but VECTOR_DIM is set to {settings.VECTOR_DIM}"
        )
```

### Database Indexes

HNSW indexes are optimized for specific dimensions. After changing dimensions:

1. Drop old indexes
2. Recreate with new dimension
3. Consider adjusting HNSW parameters (m, ef_construction) for optimal performance

## Troubleshooting

### Error: "value has X dimensions, not Y"

This means:
- Your embedding model returns X-dimensional vectors
- Your database expects Y-dimensional vectors
- Solution: Ensure `VECTOR_DIM` matches your model's output

### Performance Issues

- Ensure HNSW indexes exist (see migration `20260128_add_vector_indexes.py`)
- For very high dimensions (>2048), consider using IVFFlat instead of HNSW
- Monitor index build time and query performance

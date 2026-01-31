from __future__ import annotations
from typing import List
from loguru import logger
from ..config import settings
from ..llm.client import async_client

class GeminiEmbeddings:
    """
    Client for generating embeddings using OpenRouter (Qwen).
    Kept class name 'GeminiEmbeddings' to avoid breaking imports in services,
    but internally uses OpenAI/OpenRouter.
    """
    def __init__(self, model: str | None = None):
        self.model = model or settings.EMBEDDING_MODEL_ID
        self.client = async_client
        self._dimension_validated = False

    async def _validate_dimension(self, embedding: List[float]):
        """
        Validates that the embedding dimension matches the configured VECTOR_DIM.
        Only runs once per instance to avoid overhead.
        """
        if self._dimension_validated:
            return
        
        actual_dim = len(embedding)
        expected_dim = settings.VECTOR_DIM
        
        if actual_dim != expected_dim:
            error_msg = (
                f"Embedding dimension mismatch! "
                f"Model '{self.model}' returns {actual_dim}-dimensional vectors, "
                f"but VECTOR_DIM is configured as {expected_dim}. "
                f"Please update VECTOR_DIM in config.py or change the embedding model."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        self._dimension_validated = True
        logger.info(f"Embedding dimension validated: {actual_dim}D (model: {self.model})")

    async def embed(self, text: str, task_type: str = "retrieval_document") -> List[float]:
        """
        Compute embedding for a single text prompt.
        Note: task_type is ignored by OpenAI API standard, kept for interface compat.
        """
        try:
            # Ensure text is not empty or None
            if not text or not text.strip():
                return []

            response = await self.client.embeddings.create(
                model=self.model,
                input=text,
                encoding_format="float"
            )
            embedding = response.data[0].embedding
            
            # Validate dimension on first call
            await self._validate_dimension(embedding)
            
            return embedding
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return []

    async def embed_batch(self, texts: List[str], task_type: str = "retrieval_document") -> List[List[float]]:
        """
        Computes embeddings for a batch of texts.
        """
        if not texts:
            return []
            
        try:
            # Filter out empty strings to avoid API errors, preserve order logic if needed
            # For simplicity, we send as is, but robust code might sanitize.
            response = await self.client.embeddings.create(
                model=self.model,
                input=texts,
                encoding_format="float"
            )
            # Sort by index to ensure order matches input
            sorted_data = sorted(response.data, key=lambda x: x.index)
            embeddings = [item.embedding for item in sorted_data]
            
            # Validate dimension on first batch call
            if embeddings and not self._dimension_validated:
                await self._validate_dimension(embeddings[0])
            
            return embeddings
        except Exception as e:
            logger.error(f"Batch embedding failed: {e}")
            # Fallback to empty lists on failure
            return [[] for _ in texts]

    async def aclose(self):
        # OpenAI client manages its own connection pool
        pass
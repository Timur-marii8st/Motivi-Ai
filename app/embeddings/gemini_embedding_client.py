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
            return response.data[0].embedding
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
            return [item.embedding for item in sorted_data]
        except Exception as e:
            logger.error(f"Batch embedding failed: {e}")
            # Fallback to empty lists on failure
            return [[] for _ in texts]

    async def aclose(self):
        # OpenAI client manages its own connection pool
        pass
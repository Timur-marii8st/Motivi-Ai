from __future__ import annotations
from typing import List
from google import genai
from loguru import logger
from ..config import settings

class GeminiEmbeddings:
    """
    Client for generating embeddings using the Google Gemini API.
    """
    def __init__(self, model: str | None = None):
        self.model = model or settings.GEMINI_EMBEDDING_MODEL_ID
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)

    async def embed(self, text: str, task_type: str = "retrieval_document") -> List[float]:
        """
        Calls Gemini embeddings API to compute embedding for a single text prompt.
        """
        try:
            embed_config = genai.types.EmbedContentConfig(task_type=task_type, output_dimensionality=1536)
            # Use the asynchronous version of the embed_content method
            response = await self.client.aio.models.embed_content(
                model=self.model,
                contents=text,
                config=embed_config
            )
            return response.embeddings[0].values
        except Exception as e:
            logger.error(f"Gemini embedding failed for task type {task_type}: {e}")
            return []

    async def embed_batch(self, texts: List[str], task_type: str = "retrieval_document") -> List[List[float]]:
        """
        Computes embeddings for a batch of texts.
        """
        embeddings: List[List[float]] = []
        for t in texts:
            try:
                emb = await self.embed(t, task_type=task_type)
                embeddings.append(emb)
            except Exception as e:
                logger.error("Embedding failed for text: {} - {}", t[:80], e)
                embeddings.append([])
        return embeddings

    async def aclose(self):
        """Placeholder for API compatibility; the genai client does not require explicit closing."""
        pass
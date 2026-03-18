"""Backward-compatibility shim — import from embedding_client instead."""
from .embedding_client import EmbeddingClient, EmbeddingClient as GeminiEmbeddings  # noqa: F401

__all__ = ["GeminiEmbeddings", "EmbeddingClient"]

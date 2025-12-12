# File: app/llm/client.py

from openai import AsyncOpenAI
from ..config import settings

def get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.OPENROUTER_BASE_URL,
        api_key=settings.OPENROUTER_API_KEY,
    )

# Singleton instance
async_client = get_openai_client()

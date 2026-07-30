# File: app/llm/client.py

from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from ..config import settings


def get_openai_client() -> AsyncOpenAI:
    proxy_url = settings.OPENROUTER_PROXY_URL.strip()
    if proxy_url:
        return AsyncOpenAI(
            base_url=settings.OPENROUTER_BASE_URL,
            api_key=settings.OPENROUTER_API_KEY,
            http_client=DefaultAsyncHttpxClient(proxy=proxy_url),
        )

    return AsyncOpenAI(
        base_url=settings.OPENROUTER_BASE_URL,
        api_key=settings.OPENROUTER_API_KEY,
    )


# Singleton instance
async_client = get_openai_client()

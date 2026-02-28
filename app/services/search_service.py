"""
Web search service backed by the Tavily API with Redis result caching
and per-user rate limiting (mirrors the code_executor pattern).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone as _tz
from typing import Optional

import httpx
from loguru import logger

from ..config import settings


class SearchService:
    """
    Async web/news search via Tavily with Redis caching.

    Usage::

        results = await SearchService.search("Python async tips", num_results=5)
        allowed, count, limit = await SearchService.check_rate_limit(user_id, is_premium, is_admin)
    """

    TAVILY_URL = "https://api.tavily.com/search"

    # Shared async HTTP client (lazy-init, reused across calls)
    _client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @classmethod
    def _http(cls) -> httpx.AsyncClient:
        if cls._client is None or cls._client.is_closed:
            cls._client = httpx.AsyncClient(timeout=15.0)
        return cls._client

    @staticmethod
    def _cache_key(query: str, search_type: str, num_results: int) -> str:
        raw = f"{query.lower().strip()}:{search_type}:{num_results}"
        digest = hashlib.sha256(raw.encode()).hexdigest()[:20]
        return f"search_cache:{digest}"

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @classmethod
    async def search(
        cls,
        query: str,
        num_results: int = 5,
        search_type: str = "general",
    ) -> list[dict]:
        """
        Search the web (or news) and return a list of result dicts.

        Each dict has keys: title, url, snippet, published_date (optional).
        Returns an empty list on error or when API key is absent.
        """
        from .conversation_history_service import ConversationHistoryService

        num_results = max(1, min(10, num_results))
        cache_key = cls._cache_key(query, search_type, num_results)
        redis = ConversationHistoryService._get_redis_client()

        # Cache hit
        cached = await redis.get(cache_key)
        if cached:
            logger.debug("Search cache hit for query: '{}'", query)
            return json.loads(cached)

        if not settings.TAVILY_API_KEY:
            logger.warning("TAVILY_API_KEY is not set; web search unavailable")
            return []

        try:
            payload = {
                "api_key": settings.TAVILY_API_KEY,
                "query": query,
                "max_results": num_results,
                "topic": "news" if search_type == "news" else "general",
                "include_answer": False,
                "include_raw_content": False,
            }
            resp = await cls._http().post(cls.TAVILY_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "Tavily API error {}: {}",
                e.response.status_code,
                e.response.text[:300],
            )
            return []
        except Exception as e:
            logger.exception("Search request failed: {}", e)
            return []

        results: list[dict] = []
        for item in data.get("results", []):
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("content") or item.get("snippet", ""),
                    "published_date": item.get("published_date"),
                }
            )

        # Store in cache (TTL from config)
        await redis.setex(cache_key, settings.SEARCH_CACHE_TTL, json.dumps(results))
        logger.info("Search '{}' → {} results (type={})", query, len(results), search_type)
        return results

    @classmethod
    async def check_rate_limit(
        cls,
        user_id: int,
        is_premium: bool,
        is_admin: bool,
    ) -> tuple[bool, int, int]:
        """
        Check and increment the daily search counter for a user.

        Returns ``(allowed, current_count, daily_limit)``.
        Admins are always allowed and the counter is not incremented.
        """
        if is_admin:
            return True, 0, 99999

        from .conversation_history_service import ConversationHistoryService

        limit = (
            settings.SEARCH_DAILY_PREMIUM if is_premium else settings.SEARCH_DAILY_TRIAL
        )
        redis = ConversationHistoryService._get_redis_client()
        today = datetime.now(_tz.utc).strftime("%Y-%m-%d")
        key = f"search:{user_id}:{today}"

        count = await redis.incr(key)
        if count == 1:
            # First increment today — set key to expire at end of day + 1 h buffer
            await redis.expire(key, 86400 + 3600)

        return count <= limit, count, limit

    @classmethod
    def format_results_for_llm(cls, results: list[dict]) -> str:
        """
        Convert raw result dicts into a compact, LLM-readable text block.
        """
        if not results:
            return "No results found."

        lines: list[str] = []
        for i, r in enumerate(results, 1):
            pub = f" ({r['published_date']})" if r.get("published_date") else ""
            lines.append(
                f"{i}. [{r['title']}]({r['url']}){pub}\n   {r['snippet'][:300]}"
            )
        return "\n\n".join(lines)

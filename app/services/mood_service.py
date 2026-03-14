"""Adaptive Morning Tone — mood classification and context injection.

Classifies daily conversation mood, stores it, and provides
adaptive context for the next morning's check-in prompt.
"""
from __future__ import annotations

from datetime import datetime, timezone

import redis.asyncio as aioredis
from loguru import logger

from app.config import settings

_redis: aioredis.Redis | None = None

VALID_MOODS = frozenset({
    "positive_high_energy",
    "positive_low_energy",
    "neutral",
    "negative_low_energy",
    "negative_high_energy",
})

# Maps mood → morning prompt context modifier
MOOD_CONTEXTS: dict[str, str] = {
    "positive_high_energy": (
        "Yesterday was a great, high-energy day for the user. "
        "Lead with momentum and encourage maintaining the pace. "
        "Be enthusiastic and build on yesterday's wins."
    ),
    "positive_low_energy": (
        "Yesterday was a good but calm day. "
        "Be warm and supportive, suggest a gentle plan."
    ),
    "neutral": "",
    "negative_low_energy": (
        "Yesterday was a tough, draining day for the user. "
        "Lead with empathy and suggest a lighter, more manageable schedule. "
        "Don't pressure — be gentle and understanding."
    ),
    "negative_high_energy": (
        "Yesterday was stressful and intense for the user. "
        "Acknowledge the difficulty, suggest ways to decompress, "
        "and offer a balanced plan. Be calm and reassuring."
    ),
}


async def _get_redis() -> aioredis.Redis:
    """Lazy Redis connection."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def extract_mood(conversation_text: str) -> str:
    """Classify the emotional tone of a conversation using a lightweight LLM.

    Returns one of the VALID_MOODS strings.
    """
    if not settings.is_feature_enabled("F014_ADAPTIVE_TONE"):
        return "neutral"

    try:
        from app.llm.client import get_openai_client

        client = get_openai_client()
        response = await client.chat.completions.create(
            model=settings.EXTRACTOR_MODEL_ID,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify the emotional tone of this conversation. "
                        "Respond with EXACTLY one of: "
                        "positive_high_energy, positive_low_energy, neutral, "
                        "negative_low_energy, negative_high_energy. "
                        "Nothing else."
                    ),
                },
                {"role": "user", "content": conversation_text[:2000]},
            ],
            max_tokens=20,
            temperature=0,
        )
        mood = response.choices[0].message.content.strip().lower()
        if mood in VALID_MOODS:
            return mood
        logger.warning("LLM returned invalid mood '{}', defaulting to neutral", mood)
        return "neutral"
    except Exception:
        logger.exception("Mood extraction failed")
        return "neutral"


async def store_mood_signal(user_id: int, mood: str) -> None:
    """Store the latest mood signal in Redis (TTL: 36 hours)."""
    if not settings.is_feature_enabled("F014_ADAPTIVE_TONE"):
        return
    try:
        r = await _get_redis()
        await r.setex(f"mood:{user_id}", 36 * 3600, mood)
        logger.debug("Stored mood signal '{}' for user {}", mood, user_id)
    except Exception:
        logger.exception("Failed to store mood for user {}", user_id)


async def get_morning_mood_context(user_id: int) -> str:
    """Retrieve adaptive morning context based on yesterday's mood.

    Returns an empty string if no mood data or feature disabled.
    """
    if not settings.is_feature_enabled("F014_ADAPTIVE_TONE"):
        return ""
    try:
        r = await _get_redis()
        mood = await r.get(f"mood:{user_id}")
        if not mood or mood not in VALID_MOODS:
            return ""
        return MOOD_CONTEXTS.get(mood, "")
    except Exception:
        logger.exception("Failed to get mood context for user {}", user_id)
        return ""

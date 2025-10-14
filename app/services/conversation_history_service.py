from __future__ import annotations
import json
from typing import List
from redis.asyncio import Redis
from loguru import logger
from google.genai.types import Content, Part

from ..config import settings

class ConversationHistoryService:
    """
    Manages conversation history in Redis to provide context for the LLM.
    Stores a simplified list of role/text pairs.
    """
    _redis_client: Redis | None = None
    HISTORY_LIMIT = 10  # Max 10 messages (5 user, 5 model)
    HISTORY_EXPIRATION_SECONDS = 86400 * 7  # 24 hours * 7 days = 1 week

    @classmethod
    def _get_redis_client(cls) -> Redis:
        """Initializes and returns a singleton Redis client instance."""
        if cls._redis_client is None:
            cls._redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return cls._redis_client

    @classmethod
    async def get_history(cls, chat_id: int) -> List[Content]:
        """Retrieves and deserializes conversation history from Redis."""
        redis = cls._get_redis_client()
        key = f"conversation_history:{chat_id}"
        
        # LRANGE gets all items from the list. The history is stored chronologically.
        history_json = await redis.lrange(key, 0, -1)
        if not history_json:
            return []

        history = []
        for item in history_json:
            try:
                data = json.loads(item)
                # Reconstruct the Content object from our simplified format
                if 'role' in data and 'text' in data:
                    # Use keyword to match genai.types.Part.from_text signature
                    history.append(
                        Content(role=data['role'], parts=[Part.from_text(text=data['text'])])
                    )
            except (json.JSONDecodeError, TypeError) as e:
                # Include the raw item for easier debugging
                logger.warning(
                    "Could not deserialize history item for chat {}. item='{}' error={}",
                    chat_id,
                    item,
                    e,
                )
        
        return history

    @classmethod
    async def save_history(cls, chat_id: int, history: List[Content]):
        """
        Saves the latest conversation history to Redis in a simplified format, 
        trimming the list to the specified limit.
        """
        redis = cls._get_redis_client()
        key = f"conversation_history:{chat_id}"

        serializable_history = []
        for message in history:
            # We only store simple text-based exchanges in the short-term history.
            # This ignores complex parts like tool calls, which is fine for conversational context.
            if message.parts and hasattr(message.parts[0], 'text') and message.parts[0].text:
                simple_message = {
                    'role': message.role,
                    'text': message.parts[0].text
                }
                serializable_history.append(json.dumps(simple_message))

        if not serializable_history:
            return

        # Use a pipeline for atomic and efficient operations
        async with redis.pipeline(transaction=True) as pipe:
            pipe.delete(key) # Start fresh to ensure consistency
            # RPUSH adds items to the end of the list, preserving chronological order.
            pipe.rpush(key, *serializable_history)
            # LTRIM trims the list, keeping only the last N elements. This enforces the history limit.
            pipe.ltrim(key, -cls.HISTORY_LIMIT, -1)
            # Set an expiration on the key to automatically clean up old conversations.
            pipe.expire(key, cls.HISTORY_EXPIRATION_SECONDS)
            await pipe.execute()
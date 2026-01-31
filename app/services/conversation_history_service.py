from __future__ import annotations
import json
from typing import List, Dict, Any
from redis.asyncio import Redis
from loguru import logger

from ..config import settings

class ConversationHistoryService:
    """
    Manages conversation history in Redis to provide context for the LLM.
    Stores history as plain dicts (role + content) compatible with OpenAI API.
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
    async def get_history(cls, chat_id: int) -> List[Dict[str, str]]:
        """Retrieves and deserializes conversation history from Redis as list of dicts."""
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
                # Each item is a dict with role and content
                if 'role' in data and 'content' in data:
                    history.append(data)
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Could not deserialize history item for chat {chat_id}. Error: {e}")
        
        return history

    @classmethod
    async def save_history(cls, chat_id: int, history: List[Dict[str, Any]]):
        """
        Saves the latest conversation history to Redis, trimming to the specified limit.
        Stores only simple text-based exchanges (role + content).
        Optimized to append new messages instead of rewriting entire history.
        """
        redis = cls._get_redis_client()
        key = f"conversation_history:{chat_id}"

        # Extract only new messages (user and assistant text only)
        new_messages = []
        for message in history:
            if isinstance(message, dict):
                content = message.get("content")
                role = message.get("role")
                
                # Only save text interactions, skip tool logic and system messages
                if content and role in ["user", "assistant"]:
                    new_messages.append(json.dumps({'role': role, 'content': content}))

        if not new_messages:
            return

        # Use pipeline for atomic operations
        async with redis.pipeline(transaction=True) as pipe:
            # Append new messages to the list
            pipe.rpush(key, *new_messages)
            # Trim to keep only the last N messages
            pipe.ltrim(key, -cls.HISTORY_LIMIT, -1)
            # Refresh expiration
            pipe.expire(key, cls.HISTORY_EXPIRATION_SECONDS)
            await pipe.execute()
from __future__ import annotations
from typing import Any, Callable, Dict, Awaitable
import time
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message
from redis.asyncio import Redis
from loguru import logger

from ..config import settings

class RateLimitMiddleware(BaseMiddleware):
    """
    Distributed sliding window rate limiter using Redis.
    """
    def __init__(self):
        super().__init__()
        # Initialize a separate async Redis client for the middleware
        self.redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.limit = settings.MAX_MESSAGES_PER_MINUTE
        self.window = 60  # seconds

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Only rate limit messages from users
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        user_id = event.from_user.id
        now_ts = time.time()
        key = f"rate_limit:{user_id}"
        cutoff = now_ts - self.window

        try:
            # Use a pipeline to perform operations atomically and efficiently
            async with self.redis.pipeline(transaction=True) as pipe:
                # 1. Remove timestamps outside the current window
                pipe.zremrangebyscore(key, 0, cutoff)
                
                # 2. Add the current timestamp
                # ZADD syntax: {member: score}
                pipe.zadd(key, {str(now_ts): now_ts})
                
                # 3. Count how many messages are in the window
                pipe.zcard(key)
                
                # 4. Set key expiration to clean up inactive users automatically
                pipe.expire(key, self.window + 10)
                
                results = await pipe.execute()
                
            # results[2] is the result of ZCARD (count after adding current)
            current_count = results[2]

            if current_count > self.limit:
                logger.info(f"Rate limit exceeded for user {user_id}")
                # Optional: Don't reply every time to avoid spamming the user
                # Could check if current_count == self.limit + 1
                await event.answer(
                    f"⏱ Whoa, too fast! Please wait a moment before sending more messages."
                )
                # Stop processing the event
                return

        except Exception as e:
            logger.error(f"Rate limiter failed (failing open): {e}")
            # If Redis fails, allow the request to proceed (fail open)
            # rather than blocking all users.

        # Proceed with the handler
        return await handler(event, data)

    async def close(self):
        """Close the Redis connection."""
        await self.redis.aclose()
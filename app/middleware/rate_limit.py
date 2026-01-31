from typing import Any, Callable, Dict, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message
from redis.asyncio import Redis
from loguru import logger

from ..config import settings
from ..services.subscription_service import SubscriptionService
from ..services.profile_services import get_or_create_user
from ..db import AsyncSessionLocal

class RateLimitMiddleware(BaseMiddleware):
    """
    Two-Tier Rate Limiter:
    1. Technical (Anti-Spam): 1 msg / 2s
    2. Daily Quota: Based on Subscription Status (cached in Redis)
    
    Optimized to minimize DB connections by caching subscription status.
    """
    def __init__(self):
        super().__init__()
        self.redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.CACHE_TTL = 300  # Cache subscription status for 5 minutes

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        # Allow /subscribe and /start always to prevent soft-locks
        if event.text and any(event.text.startswith(cmd) for cmd in ["/subscribe", "/start", "/help"]):
             return await handler(event, data)

        tg_user_id = event.from_user.id
        
        # --- Tier A: Technical Limit (Anti-Spam) ---
        tech_key = f"throttle:{tg_user_id}"
        
        is_allowed_tech = await self.redis.set(
            tech_key, 
            "1", 
            nx=True, 
            ex=settings.LIMIT_TECHNICAL_SECONDS
        )
        
        if not is_allowed_tech:
            logger.debug(f"Technical limit hit for {tg_user_id}")
            return 

        # --- Tier B: Daily Quota (with cached subscription status) ---
        # Try to get cached subscription info
        cache_key = f"sub_cache:{tg_user_id}"
        cached_data = await self.redis.get(cache_key)
        
        if cached_data:
            # Parse cached data: "status:limit"
            try:
                status, limit_str = cached_data.split(":", 1)
                limit = int(limit_str)
            except (ValueError, AttributeError):
                # Cache corrupted, will refresh below
                cached_data = None
        
        if not cached_data:
            # Cache miss - fetch from DB
            async with AsyncSessionLocal() as session:
                user = await get_or_create_user(session, tg_user_id, event.chat.id)
                status = await SubscriptionService.get_user_status(user)
                
                # Determine limit
                if status == "admin":
                    limit = 999999
                elif status == "premium":
                    limit = settings.LIMIT_DAILY_PREMIUM
                elif status == "trial":
                    limit = settings.LIMIT_DAILY_TRIAL
                else:  # expired
                    limit = settings.LIMIT_DAILY_EXPIRED
                
                # Cache the result
                await self.redis.set(cache_key, f"{status}:{limit}", ex=self.CACHE_TTL)
        
        # Check quota using cached/fetched status
        if status == "admin":
            # Admins bypass quota
            return await handler(event, data)
        
        # Check Redis counter
        today_str = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime("%Y-%m-%d")
        quota_key = f"quota:{tg_user_id}:{today_str}"
        
        current_usage = await self.redis.incr(quota_key)
        
        if current_usage == 1:
            await self.redis.expire(quota_key, 86400 + 3600)
        
        if current_usage > limit:
            # Quota exceeded
            if status == "expired":
                msg = (
                    f"⛔️ <b>Free Trial Ended</b>\n\n"
                    f"Your 7-day trial has expired. To continue using Motivi_AI, please subscribe.\n\n"
                    f"Use /subscribe to unlock unlimited access."
                )
            else:  # status == 'trial'
                msg = (
                    f"🔒 <b>Daily Limit Reached ({limit}/{limit})</b>\n\n"
                    f"You are on the Free Trial. Upgrade to Premium for {settings.LIMIT_DAILY_PREMIUM} messages/day.\n"
                    f"Use /subscribe to upgrade."
                )
            
            await event.answer(msg)
            return

        return await handler(event, data)

    async def close(self):
        await self.redis.aclose()
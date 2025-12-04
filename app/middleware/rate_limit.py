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
    2. Daily Quota: Based on Subscription Status
    """
    def __init__(self):
        super().__init__()
        self.redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)

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
        # Key expires in LIMIT_TECHNICAL_SECONDS. If exists, we block.
        tech_key = f"throttle:{tg_user_id}"
        
        # set(nx=True) returns True if key was set (user allowed), None if key exists (blocked)
        is_allowed_tech = await self.redis.set(
            tech_key, 
            "1", 
            nx=True, 
            ex=settings.LIMIT_TECHNICAL_SECONDS
        )
        
        if not is_allowed_tech:
            # Silent ignore or minimal "too fast" log
            logger.debug(f"Technical limit hit for {tg_user_id}")
            # Optional: await event.answer("🚦 Too fast!")
            return 

        # --- Tier B: Daily Quota ---
        # We need to fetch the user from DB to check status.
        # We create a local session because DBSessionMiddleware runs AFTER this.
        async with AsyncSessionLocal() as session:
            # This ensures user exists and we have their subscription data
            user = await get_or_create_user(session, tg_user_id, event.chat.id)
            
            allowed, status, usage, limit = await SubscriptionService.check_quota(user, self.redis)

            if not allowed:
                # Quota exceeded handling
                if status == "expired":
                    msg = (
                        f"⛔️ <b>Free Trial Ended</b>\n\n"
                        f"Your 7-day trial has expired. To continue using Motivi_AI, please subscribe.\n\n"
                        f"Use /subscribe to unlock unlimited access."
                    )
                else: # status == 'trial'
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
from datetime import datetime, timezone, timedelta
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from ..config import settings
from ..models.users import User

class SubscriptionService:
    @staticmethod
    async def get_user_status(user: User) -> str:
        """
        Returns: 'admin', 'premium', 'trial', or 'expired'
        """
        if user.tg_user_id in settings.admin_ids:
            return "admin"
        
        if user.is_premium:
            return "premium"
            
        if user.is_trial:
            return "trial"
            
        return "expired"

    @staticmethod
    async def check_quota(user: User, redis: Redis) -> tuple[bool, str, int, int]:
        """
        Checks daily message quota.
        Returns: (is_allowed, status, current_usage, max_limit)
        """
        status = await SubscriptionService.get_user_status(user)
        
        # 1. Define Limits based on Status
        if status == "admin":
            return True, status, 0, 999999
        elif status == "premium":
            limit = settings.LIMIT_DAILY_PREMIUM
        elif status == "trial":
            limit = settings.LIMIT_DAILY_TRIAL
        else: # expired
            limit = settings.LIMIT_DAILY_EXPIRED

        # 2. Check Redis Counter (Key: quota:user_id:YYYY-MM-DD)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"quota:{user.id}:{today_str}"

        # Atomic increment
        current_usage = await redis.incr(key)
        
        # Set expiry (24h + 1h buffer) only on first write
        if current_usage == 1:
            await redis.expire(key, 86400 + 3600)

        # 3. Validation
        if current_usage > limit:
            return False, status, current_usage, limit

        return True, status, current_usage, limit

    @staticmethod
    async def add_subscription_time(session: AsyncSession, user: User, months: int = 1):
        """Adds 30 days * months to the subscription."""
        now = datetime.now(timezone.utc)
        
        # Extend existing or start new
        if user.subscription_ends_at and user.subscription_ends_at > now:
            start_date = user.subscription_ends_at
        else:
            start_date = now
            
        new_end_date = start_date + timedelta(days=30 * months)
        
        user.subscription_ends_at = new_end_date
        user.touch()
        session.add(user)
        # Note: Commit is handled by the caller/middleware
        logger.info(f"User {user.id} subscription extended until {new_end_date}")
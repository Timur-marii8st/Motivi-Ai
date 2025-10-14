from __future__ import annotations
import json
import secrets
from redis.asyncio import Redis
from ..config import settings

class OAuthStateService:
    """
    Manages secure, short-lived OAuth state tokens using Redis to prevent CSRF.
    """
    _redis_client: Redis | None = None
    STATE_EXPIRATION_SECONDS = 600  # 10 minutes

    @classmethod
    def _get_redis_client(cls) -> Redis:
        """Initializes and returns a singleton Redis client instance."""
        if cls._redis_client is None:
            cls._redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return cls._redis_client

    @classmethod
    async def create_and_store_state(cls, user_id: int, chat_id: int) -> str:
        """
        Generates a secure, unguessable state token and stores user info against it in Redis.
        """
        redis = cls._get_redis_client()
        state_token = secrets.token_urlsafe(32)
        
        payload = {
            "user_id": user_id,
            "chat_id": chat_id,
        }
        
        await redis.set(
            f"oauth_state:{state_token}",
            json.dumps(payload),
            ex=cls.STATE_EXPIRATION_SECONDS
        )
        return state_token

    @classmethod
    async def verify_and_consume_state(cls, state_token: str) -> dict | None:
        """
        Verifies the state token exists in Redis, retrieves the payload, and deletes the token.
        Returns the user info payload if valid, otherwise None.
        """
        redis = cls._get_redis_client()
        key = f"oauth_state:{state_token}"
        
        payload_str = await redis.get(key)
        
        if not payload_str:
            return None # State is invalid or expired
            
        # Consume the token to prevent reuse
        await redis.delete(key)
        
        return json.loads(payload_str)  
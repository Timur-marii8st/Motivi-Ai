from __future__ import annotations
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from ..config import settings
from .middlewares.db_session import DBSessionMiddleware
from ..middleware.rate_limit import RateLimitMiddleware
from .routers.onboarding import router as onboarding_router
from .routers.oauth import router as oauth_router
from .routers.habits import router as habits_router
from .routers.multimodal import router as multimodal_router
from .routers.profile import router as profile_router
from .routers.settings import router as settings_router
from .routers.break_mode import router as break_mode_router
from .routers.admin import router as admin_router
from .routers.chat import router as chat_router
from .routers.common import router as common_router

def create_bot_and_dispatcher() -> tuple[Bot, Dispatcher]:
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))

    redis_client = Redis.from_url(settings.REDIS_URL)
    
    # Use RedisStorage for persistent FSM state across workers/restarts
    storage = RedisStorage(redis=redis_client)
    
    dp = Dispatcher(storage=storage)

    # Middlewares
    dp.message.middleware(RateLimitMiddleware())
    dp.message.middleware(DBSessionMiddleware())
    dp.callback_query.middleware(DBSessionMiddleware())

    # Routers
    dp.include_router(onboarding_router)
    dp.include_router(oauth_router)
    dp.include_router(habits_router)
    dp.include_router(profile_router)
    dp.include_router(settings_router)
    dp.include_router(break_mode_router)
    dp.include_router(admin_router)
    dp.include_router(multimodal_router)
    dp.include_router(chat_router)
    dp.include_router(common_router)
    
    # Note: The redis_client created here will be closed automatically 
    # by aiogram when the dispatcher is shut down.
    
    return bot, dp
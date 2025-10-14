from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlmodel import SQLModel, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from loguru import logger

from .config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True, pool_pre_ping=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db() -> None:
    """Create tables and enable pgvector extension."""
    from .models.users import User
    from .models.core_memory import CoreMemory
    from .models.working_memory import WorkingMemory
    from .models.episode import Episode, EpisodeEmbedding
    from .models.task import Task
    from .models.settings import UserSettings
    from .models.habit import Habit, HabitLog
    from .models.oauth_token import OAuthToken
    from .models.profile_completeness import ProfileCompleteness
    from .models.habit import Habit, HabitLog
    from .models.oauth_token import OAuthToken

    async with engine.begin() as conn:
        # Enable pgvector
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        logger.info("pgvector extension enabled")
        # Create all tables
        await conn.run_sync(SQLModel.metadata.create_all)
        logger.info("Database tables created/verified")

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlmodel import SQLModel, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import event
from loguru import logger

from .config import settings
from .security.row_integrity import register_row_integrity_hooks

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10,
    pool_recycle=3600,
    pool_timeout=10,
    connect_args={"command_timeout": 30},
)


@event.listens_for(engine.sync_engine, "connect")
def set_timezone(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("SET timezone='UTC'")
    cursor.close()


AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
register_row_integrity_hooks()


async def init_db() -> None:
    """Create tables and enable pgvector extension."""
    from .models.users import User  # noqa: F401
    from .models.core_memory import CoreMemory  # noqa: F401
    from .models.working_memory import WorkingMemory  # noqa: F401
    from .models.episode import Episode, EpisodeEmbedding  # noqa: F401
    from .models.settings import UserSettings  # noqa: F401
    from .models.habit import Habit, HabitLog  # noqa: F401
    from .models.oauth_token import OAuthToken  # noqa: F401
    from .models.payment import Payment  # noqa: F401
    from .models.profile_completeness import ProfileCompleteness  # noqa: F401
    from .models.plan import Plan  # noqa: F401
    from .models.user_trigger import UserTrigger  # noqa: F401
    from .models.userbot_thread import UserBotThread  # noqa: F401

    async with engine.begin() as conn:
        # Enable pgvector
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        logger.info("pgvector extension enabled")
        # In development only: create missing tables automatically for convenience.
        # In production we rely on Alembic migrations (do not call create_all there).
        if settings.ENV == "dev":
            await conn.run_sync(SQLModel.metadata.create_all)
            logger.info("Database tables created/verified (dev mode)")
        else:
            logger.info("Skipping SQLModel.metadata.create_all (ENV=%s)", settings.ENV)


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

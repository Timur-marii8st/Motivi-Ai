from logging.config import fileConfig

import asyncio
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import the project's settings and SQLModel metadata
from sqlmodel import SQLModel
from app.config import settings

# Ensure your models are imported so they are registered on SQLModel.metadata
# This mirrors what `init_db()` does and allows alembic autogenerate to see models
from app.models.users import User  # noqa: F401
from app.models.core_memory import CoreMemory  # noqa: F401
from app.models.working_memory import WorkingMemory  # noqa: F401
from app.models.episode import Episode, EpisodeEmbedding  # noqa: F401
from app.models.settings import UserSettings  # noqa: F401
from app.models.habit import Habit, HabitLog  # noqa: F401
from app.models.oauth_token import OAuthToken  # noqa: F401
from app.models.profile_completeness import ProfileCompleteness  # noqa: F401
from app.models.plan import Plan

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""

    url = settings.DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations using the given (sync) connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and name == "apscheduler_jobs":
        return False
    return True


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an AsyncEngine."""

    connectable = create_async_engine(
        settings.DATABASE_URL,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        # Run migrations in a synchronous context against the connection
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

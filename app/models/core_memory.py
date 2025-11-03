from typing import Optional, TYPE_CHECKING
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Column, JSON, UniqueConstraint, Relationship
from sqlalchemy import Text, DateTime
from pgvector.sqlalchemy import Vector

if TYPE_CHECKING:
    from .users import User

class CoreMemory(SQLModel, table=True):
    __tablename__ = "core_memory"
    __table_args__ = (UniqueConstraint("user_id", name="uq_core_memory_user"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    # Use a plain Python type for annotations so pydantic can generate a schema.
    # Keep the SQLAlchemy Text column via `sa_column` so the DB column is Text.
    core_text: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))    
    sleep_schedule_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))

    # Use timezone-aware UTC datetimes and a timezone-aware DB column.
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    user: "User" = Relationship(back_populates="core_memory")

class CoreEmbedding(SQLModel, table=True):
    """
    Stores vector embeddings for core memory using pgvector.
    """
    __tablename__ = "core_memory_embeddings"

    id: Optional[int] = Field(default=None, primary_key=True)
    core_memory_id: int = Field(unique=True, foreign_key="core_memory.id", index=True)

    # Annotate as list[float] (embedding vector) so pydantic can validate the field.
    embedding: list[float] = Field(sa_column=Column(Vector(1536), nullable=False))

    # Use timezone-aware UTC datetimes and a timezone-aware DB column for embeddings.
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
from typing import Optional, TYPE_CHECKING
from datetime import datetime, timezone, date
from sqlmodel import SQLModel, Field, UniqueConstraint, Relationship
from sqlalchemy import DateTime, Column
from pgvector.sqlalchemy import Vector

from ..security.encrypted_types import EncryptedTextType

if TYPE_CHECKING:
    from .users import User

class WorkingMemory(SQLModel, table=True):
    """
    Short-term context: recent goals, events, summary.
    Refreshed weekly; decays after `decay_date`.
    """
    __tablename__ = "working_memory"
    __table_args__ = (UniqueConstraint("user_id", name="uq_working_memory_user"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")

    working_memory_text: Optional[str] = Field(
        default=None,
        max_length=2000,
        sa_column=Column(
            EncryptedTextType("working_memory.working_memory_text"),
            nullable=True,
        ),
    )
    history_order: Optional[int] = Field(default=None, index=True)

    decay_date: Optional[date] = Field(default=None, index=True)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    user: "User" = Relationship(back_populates="working_memory")


class WorkingMemoryEntry(SQLModel, table=True):
    """
    Historical working memory entries. One row per entry per user.
    Newest entry should have history_order=1.
    """
    __tablename__ = "working_memory_entry"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")

    working_memory_text: Optional[str] = Field(
        default=None,
        max_length=2000,
        sa_column=Column(
            EncryptedTextType("working_memory_entry.working_memory_text"),
            nullable=True,
        ),
    )
    history_order: Optional[int] = Field(default=None, index=True)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class WorkingEntryEmbedding(SQLModel, table=True):
    __tablename__ = "working_memory_entry_embeddings"

    id: Optional[int] = Field(default=None, primary_key=True)
    working_entry_id: int = Field(unique=True, foreign_key="working_memory_entry.id", index=True)

    embedding: list = Field(sa_column=Column(Vector(1536), nullable=False))

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

class WorkingEmbedding(SQLModel, table=True):
    """
    Stores vector embeddings for working memory using pgvector.
    """
    __tablename__ = "working_memory_embeddings"

    id: Optional[int] = Field(default=None, primary_key=True)
    working_memory_id: int = Field(unique=True, foreign_key="working_memory.id", index=True)

    embedding: list = Field(sa_column=Column(Vector(1536), nullable=False))

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
from typing import Optional, TYPE_CHECKING
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, UniqueConstraint, Relationship
from sqlalchemy import DateTime, Column
from pgvector.sqlalchemy import Vector

from ..security.encrypted_types import EncryptedTextType, EncryptedJSONType

if TYPE_CHECKING:
    from .users import User

class CoreMemory(SQLModel, table=True):
    __tablename__ = "core_memory"
    __table_args__ = (UniqueConstraint("user_id", name="uq_core_memory_user"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    # Use a plain Python type for annotations so pydantic can generate a schema.
    # Keep the SQLAlchemy Text column via `sa_column` so the DB column is Text.
    # NOTE: `core_text` historically stored a plain text string. We now store
    # a JSON-encoded list of objects: [{"fact": "text", "created_at": "iso"}, ...]
    # To remain backward compatible, code reading `core_text` should detect
    # JSON list vs. plain string and handle both.
    core_text: Optional[str] = Field(
        default=None,
        sa_column=Column(EncryptedTextType("core_memory.core_text"), nullable=True),
    )
    sleep_schedule_json: Optional[dict] = Field(
        default=None,
        sa_column=Column(EncryptedJSONType("core_memory.sleep_schedule")),
    )

    # Use timezone-aware UTC datetimes and a timezone-aware DB column.
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    user: "User" = Relationship(back_populates="core_memory")
    facts: list["CoreFact"] = Relationship(back_populates="core_memory")

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


class CoreFact(SQLModel, table=True):
    """
    Per-fact model to store individual core facts. Each fact is a row and can be
    embedded and retrieved independently.
    """
    __tablename__ = "core_facts"

    id: Optional[int] = Field(default=None, primary_key=True)
    core_memory_id: int = Field(index=True, foreign_key="core_memory.id")
    fact_text: str = Field(sa_column=Column(EncryptedTextType("core_facts.fact_text"), nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    core_memory: "CoreMemory" = Relationship(back_populates="facts")


class CoreFactEmbedding(SQLModel, table=True):
    """Embedding vectors for CoreFact rows, used for semantic retrieval."""
    __tablename__ = "core_fact_embeddings"

    id: Optional[int] = Field(default=None, primary_key=True)
    core_fact_id: int = Field(unique=True, foreign_key="core_facts.id", index=True)
    embedding: list[float] = Field(sa_column=Column(Vector(1536), nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
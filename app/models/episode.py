from typing import Optional, TYPE_CHECKING
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Column, JSON, Relationship
from sqlalchemy import Text, DateTime
from pgvector.sqlalchemy import Vector


if TYPE_CHECKING:
    from .users import User

class Episode(SQLModel, table=True):
    """
    Immutable event/memory: daily summaries, completed tasks, milestones.
    Vectorized for semantic retrieval.
    """
    __tablename__ = "episodes"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    user: "User" = Relationship(back_populates="episodes")

    text: str = Field(sa_column=Column(Text, nullable=False))
    metadata_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))

    created_at: datetime = Field(
        sa_column=Column("created_at", DateTime(timezone=True), nullable=False, index=True),
        default_factory=lambda: datetime.now(timezone.utc)
    )


class EpisodeEmbedding(SQLModel, table=True):
    """
    Stores vector embeddings for episodes using pgvector.
    """
    __tablename__ = "episode_embeddings"

    id: Optional[int] = Field(default=None, primary_key=True)
    episode_id: int = Field(unique=True, foreign_key="episodes.id", index=True)

    embedding: list = Field(sa_column=Column(Vector(1536), nullable=False))

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), nullable=False)
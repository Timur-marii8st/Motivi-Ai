from typing import Optional, TYPE_CHECKING
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, DateTime

from ..security.encrypted_types import EncryptedTextType


if TYPE_CHECKING:
    from .users import User

class Task(SQLModel, table=True):
    """
    User tasks: manually created or extracted from plans.
    """
    __tablename__ = "tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    user: "User" = Relationship(back_populates="tasks")

    title: str = Field(max_length=200)
    description: Optional[str] = Field(
        default=None,
        sa_column=Column(EncryptedTextType("tasks.description"), nullable=True),
    )
    status: str = Field(default="todo", max_length=20, index=True)  # todo, doing, done

    due_dt: Optional[datetime] = Field(default=None, index=True)
    created_from_plan: bool = Field(default=False)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
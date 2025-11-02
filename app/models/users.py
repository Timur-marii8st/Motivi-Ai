from typing import Optional, List, TYPE_CHECKING
from datetime import datetime, timezone, time
from sqlmodel import SQLModel, Field, Column, JSON, UniqueConstraint, Relationship


if TYPE_CHECKING:
    from .core_memory import CoreMemory
    from .working_memory import WorkingMemory
    from .settings import UserSettings
    from .profile_completeness import ProfileCompleteness
    from .episode import Episode
    from .task import Task
    from .habit import Habit
    from .oauth_token import OAuthToken


class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tg_user_id", name="uq_users_tg_user_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    tg_user_id: int = Field(index=True)
    tg_chat_id: int = Field(index=True)

    name: Optional[str] = None
    age: Optional[int] = None

    user_timezone: Optional[str] = Field(default=None, index=True)
    wake_time: Optional[time] = None
    bed_time: Optional[time] = None

    occupation_json: Optional[dict] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), nullable=False)

    # --- Relationships ---
    # One-to-One relationships
    core_memory: Optional["CoreMemory"] = Relationship(back_populates="user", sa_relationship_kwargs={"uselist": False})
    working_memory: Optional["WorkingMemory"] = Relationship(back_populates="user", sa_relationship_kwargs={"uselist": False})
    settings: Optional["UserSettings"] = Relationship(back_populates="user", sa_relationship_kwargs={"uselist": False})
    profile_completeness: Optional["ProfileCompleteness"] = Relationship(back_populates="user", sa_relationship_kwargs={"uselist": False})

    # One-to-Many relationships
    episodes: List["Episode"] = Relationship(back_populates="user")
    tasks: List["Task"] = Relationship(back_populates="user")
    habits: List["Habit"] = Relationship(back_populates="user")
    oauth_tokens: List["OAuthToken"] = Relationship(back_populates="user")

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)
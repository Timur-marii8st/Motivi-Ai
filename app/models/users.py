from typing import Optional, List, TYPE_CHECKING
from datetime import datetime, timezone, time, timedelta
from sqlmodel import SQLModel, Field, UniqueConstraint, Relationship
from sqlalchemy import DateTime, Column
from ..config import settings

from ..security.encrypted_types import EncryptedTextType, EncryptedJSONType


if TYPE_CHECKING:
    from .core_memory import CoreMemory
    from .working_memory import WorkingMemory
    from .settings import UserSettings
    from .profile_completeness import ProfileCompleteness
    from .episode import Episode
    from .habit import Habit
    from .oauth_token import OAuthToken
    from .plan import Plan


class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tg_user_id", name="uq_users_tg_user_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    tg_user_id: int = Field(index=True)
    tg_chat_id: int = Field(index=True)

    name: Optional[str] = Field(
        default=None,
        sa_column=Column(EncryptedTextType("users.name"), nullable=True),
    )
    age: Optional[int] = None

    user_timezone: Optional[str] = Field(default=None, index=True)
    wake_time: Optional[time] = None
    bed_time: Optional[time] = None

    occupation_json: Optional[dict] = Field(
        default=None,
        sa_column=Column(EncryptedJSONType("users.occupation")),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    subscription_ends_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )

    # --- Relationships ---
    # One-to-One relationships
    core_memory: Optional["CoreMemory"] = Relationship(back_populates="user", sa_relationship_kwargs={"uselist": False})
    working_memory: Optional["WorkingMemory"] = Relationship(back_populates="user", sa_relationship_kwargs={"uselist": False})
    settings: Optional["UserSettings"] = Relationship(back_populates="user", sa_relationship_kwargs={"uselist": False})
    profile_completeness: Optional["ProfileCompleteness"] = Relationship(back_populates="user", sa_relationship_kwargs={"uselist": False})

    # One-to-Many relationships
    episodes: List["Episode"] = Relationship(back_populates="user")
    habits: List["Habit"] = Relationship(back_populates="user")
    oauth_tokens: List["OAuthToken"] = Relationship(back_populates="user")
    plans: List["Plan"] = Relationship(back_populates="user")

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    @property
    def is_premium(self) -> bool:
        """Check if subscription is active."""
        if self.subscription_ends_at:
            return self.subscription_ends_at > datetime.now(timezone.utc)
        return False
    
    @property
    def is_trial(self) -> bool:
        """Check if user is within the 7-day trial period."""
        if self.is_premium:
            return False
        
        # Trial expires TRIAL_DAYS after creation
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.TRIAL_DAYS)
        return self.created_at > cutoff

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)
from typing import Optional, TYPE_CHECKING
from datetime import datetime, timezone, timedelta
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, DateTime

from ..security.encrypted_types import EncryptedTextType


if TYPE_CHECKING:
    from .users import User


class Plan(SQLModel, table=True):
    """
    User plans: daily, weekly, or monthly plans stored temporarily in memory.
    Plans automatically expire based on their level.
    """
    __tablename__ = "plans"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    user: "User" = Relationship(back_populates="plans")

    plan_level: str = Field(max_length=20, index=True)  # daily, weekly, monthly
    content: str = Field(
        sa_column=Column(EncryptedTextType("plans.content"), nullable=False),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )

    @staticmethod
    def calculate_expiry(plan_level: str) -> datetime:
        """Calculate expiry time based on plan level."""
        now = datetime.now(timezone.utc)
        if plan_level == "daily":
            return now + timedelta(days=1)
        elif plan_level == "weekly":
            return now + timedelta(days=7)
        elif plan_level == "monthly":
            return now + timedelta(days=30)
        else:
            # Default to daily if invalid level
            return now + timedelta(days=1)

    def is_expired(self) -> bool:
        """Check if plan has expired."""
        return datetime.now(timezone.utc) > self.expires_at

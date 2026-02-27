from __future__ import annotations
from typing import Optional
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, DateTime, Text


class UserTrigger(SQLModel, table=True):
    """User-defined custom proactive flow triggers with a cron-style schedule."""
    __tablename__ = "user_triggers"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")

    # Human-readable label shown in /triggers list
    name: str = Field(max_length=100)
    # The prompt sent to the LLM when this trigger fires
    prompt: str = Field(sa_column=Column(Text, nullable=False))

    # Cron schedule in the user's local timezone
    cron_hour: int       # 0-23
    cron_minute: int = Field(default=0)    # 0-59
    # Optional APScheduler day-of-week string, e.g. "mon,wed,fri" or None (= every day)
    cron_weekdays: Optional[str] = Field(default=None, max_length=50)

    active: bool = Field(default=True)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

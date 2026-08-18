from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String
from sqlmodel import Field, SQLModel

from ..security.encrypted_types import EncryptedTextType


class CalendarEvent(SQLModel, table=True):
    """Internal Motivi calendar event.

    Events are created automatically by the userbot pipeline (LLM extraction
    from incoming DMs, group messages and channel posts), via the LLM
    ``add_calendar_event`` tool, or manually. Each active event carries a
    one-off APScheduler reminder job.
    """

    __tablename__ = "calendar_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")

    title: str = Field(
        sa_column=Column(EncryptedTextType("calendar_events.title"), nullable=False),
    )
    description: Optional[str] = Field(
        default=None,
        sa_column=Column(
            EncryptedTextType("calendar_events.description"), nullable=True
        ),
    )

    starts_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    ends_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    all_day: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    # Origin of the event: "dm", "group", "channel", "chat" (LLM tool), "manual"
    source_type: str = Field(
        default="manual",
        sa_column=Column(
            String(20), nullable=False, index=True, server_default="manual"
        ),
    )
    source_name: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    source_chat_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True, index=True),
    )
    source_message_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )

    # "active", "done", "cancelled"
    status: str = Field(
        default="active",
        sa_column=Column(
            String(20), nullable=False, index=True, server_default="active"
        ),
    )

    remind_before_minutes: int = Field(
        default=15,
        sa_column=Column(Integer, nullable=False, server_default="15"),
    )
    reminded_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    reminder_job_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(100), nullable=True),
    )

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

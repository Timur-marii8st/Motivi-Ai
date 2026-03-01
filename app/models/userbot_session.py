from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel

from ..security.encrypted_types import EncryptedTextType


class UserBotSession(SQLModel, table=True):
    """
    Stores the Telethon StringSession for a user's connected personal
    Telegram account. There is at most one active session per bot-user.
    Both the session string and phone number are encrypted at rest.
    """

    __tablename__ = "userbot_sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", unique=True, index=True)

    # Telethon StringSession.save() output — encrypted
    session_string: Optional[str] = Field(
        default=None,
        sa_column=Column(
            EncryptedTextType("userbot_sessions.session_string"), nullable=True
        ),
    )

    # E.164 phone number used during auth — encrypted
    phone_number: Optional[str] = Field(
        default=None,
        sa_column=Column(
            EncryptedTextType("userbot_sessions.phone_number"), nullable=True
        ),
    )

    is_active: bool = Field(default=True)

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

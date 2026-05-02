from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String
from sqlmodel import Field, SQLModel

from ..security.encrypted_types import EncryptedJSONType, EncryptedTextType


class UserBotThread(SQLModel, table=True):
    """Tracked userbot conversation item that may need a reply/follow-up."""

    __tablename__ = "userbot_threads"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    chat_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    chat_type: str = Field(
        default="dm",
        sa_column=Column(String(20), nullable=False, index=True),
    )
    sender_tg_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True, index=True),
    )
    sender_name: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    message_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, index=True),
    )
    message_text: Optional[str] = Field(
        default=None,
        sa_column=Column(
            EncryptedTextType("userbot_threads.message_text"), nullable=True
        ),
    )
    message_summary: Optional[str] = Field(
        default=None,
        sa_column=Column(
            EncryptedTextType("userbot_threads.message_summary"), nullable=True
        ),
    )
    suggested_replies_json: Optional[list] = Field(
        default=None,
        sa_column=Column(
            EncryptedJSONType("userbot_threads.suggested_replies"), nullable=True
        ),
    )
    status: str = Field(
        default="new",
        sa_column=Column(String(30), nullable=False, index=True),
    )
    importance: int = Field(
        default=3,
        sa_column=Column(Integer, nullable=False, index=True),
    )
    requires_response: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    memory_worthy: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    memory_items_json: Optional[list] = Field(
        default=None,
        sa_column=Column(
            EncryptedJSONType("userbot_threads.memory_items"), nullable=True
        ),
    )
    response_deadline_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    reminded_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_incoming_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    last_outgoing_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
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

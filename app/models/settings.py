from typing import Optional, TYPE_CHECKING
from datetime import datetime, timezone, time
from sqlmodel import SQLModel, Field, UniqueConstraint, Relationship
from sqlalchemy import DateTime, Column, String

from ..security.encrypted_types import EncryptedJSONType


if TYPE_CHECKING:
    from .users import User

class UserSettings(SQLModel, table=True):
    """
    User preferences for notifications, proactivity, and break mode.
    """
    __tablename__ = "user_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_settings_user"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    user: "User" = Relationship(back_populates="settings")

    # Notification windows (can override user wake/bed times for messaging)
    morning_window_start: Optional[time] = None  # If None, use user.wake_time
    morning_window_end: Optional[time] = None    # E.g., wake + 2 hours
    evening_window_start: Optional[time] = None  # E.g., bed - 2 hours
    evening_window_end: Optional[time] = None    # If None, use user.bed_time

    # Break mode
    break_mode_active: bool = Field(default=False)
    break_mode_until: Optional[datetime] = Field(default=None, index=True)

    # Proactivity toggles
    enable_morning_checkin: bool = Field(default=True)
    enable_evening_wrapup: bool = Field(default=True)
    enable_weekly_plan: bool = Field(default=True)
    enable_monthly_plan: bool = Field(default=True)
    # News digest: opt-in, fires NEWS_DIGEST_OFFSET_MINUTES after wake_time
    enable_news_digest: bool = Field(default=False)

    # --- User Bot (MTProto monitoring) ---
    # Whether to send a notification when an interesting channel post arrives
    enable_channel_monitoring: bool = Field(default=True)
    # Whether to send a notification with reply suggestions for incoming DMs
    enable_dm_notifications: bool = Field(default=True)
    # Whether to monitor group/supergroup messages and suggest replies
    enable_group_monitoring: bool = Field(default=False)
    # Whether to show approval buttons on DM/group reply suggestions
    enable_reply_approval: bool = Field(default=True)
    # Free-text description of topics the user finds interesting (fed to LLM filter)
    userbot_channel_interests: Optional[str] = Field(default=None)

    # Bot persona: controls which system prompt style is used
    # Values: "strict", "friendly", "coach", "zen", "hype"
    bot_persona: str = Field(
        default="strict",
        sa_column=Column(String(30), nullable=False, server_default="strict"),
    )

    # ── Gamification toggles ────────────────────────────────
    show_on_leaderboard: bool = Field(default=True)
    hide_streak: bool = Field(default=False)

    # Persona customization (premium): tone, emoji_density, response_length
    persona_preferences_json: Optional[dict] = Field(
        default=None,
        sa_column=Column(EncryptedJSONType("user_settings.persona_preferences")),
    )

    # Summary content preferences
    summary_preferences_json: Optional[dict] = Field(
        default=None,
        sa_column=Column(EncryptedJSONType("user_settings.summary_preferences")),
    )  # e.g., {"include_habits": true, "include_calendar": true}
    integrity_sig: Optional[str] = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
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

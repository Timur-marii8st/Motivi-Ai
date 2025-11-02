from typing import Optional, TYPE_CHECKING
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, UniqueConstraint, Relationship
from sqlalchemy import Text, Column, DateTime

if TYPE_CHECKING:
    from .users import User

class OAuthToken(SQLModel, table=True):
    """
    Stores encrypted OAuth tokens for external services (Google Calendar, etc).
    """
    __tablename__ = "oauth_tokens"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_oauth_tokens_user_provider"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    user: "User" = Relationship(back_populates="oauth_tokens")
    
    provider: str = Field(max_length=50, index=True)  # e.g., 'google_calendar'
    
    # Encrypted token blob (JSON with access_token, refresh_token, expiry, etc.)
    encrypted_token_blob: str = Field(sa_column=Column(Text, nullable=False))
    
    token_expiry: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
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
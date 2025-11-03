from typing import Optional, TYPE_CHECKING
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, UniqueConstraint, Relationship
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import TIMESTAMP


if TYPE_CHECKING:
    from .users import User

class ProfileCompleteness(SQLModel, table=True):
    """
    Tracks profile completeness and question frequency for adaptive behavior.
    """
    __tablename__ = "profile_completeness"
    __table_args__ = (UniqueConstraint("user_id", name="uq_profile_completeness_user"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    user: "User" = Relationship(back_populates="profile_completeness")

    # Completeness score (0.0 - 1.0)
    score: float = Field(default=0.0)
    
    # Question frequency multiplier (1.0 = normal, decays over time)
    question_frequency: float = Field(default=1.0)
    
    # Tracking
    total_questions_asked: int = Field(default=0)
    total_interactions: int = Field(default=0)
    last_profile_update: Optional[datetime] = None
    
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(TIMESTAMP(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(TIMESTAMP(timezone=True), nullable=False)
    )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)
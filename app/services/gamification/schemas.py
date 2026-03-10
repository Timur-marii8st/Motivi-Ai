"""Shared contracts for the gamification subsystem.

Every agent and service that emits or consumes gamification events MUST
use the types defined here.  No magic strings — always reference enums.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


# ─── Event Bus ────────────────────────────────────────────────────
class GameEventType(str, Enum):
    MESSAGE_SENT = "message_sent"
    HABIT_LOGGED = "habit_logged"
    PLAN_CREATED = "plan_created"
    STREAK_UPDATED = "streak_updated"
    STREAK_MILESTONE = "streak_milestone"
    CHALLENGE_COMPLETED = "challenge_completed"
    FEATURE_FIRST_USE = "feature_first_use"
    CODE_EXECUTED = "code_executed"
    WEB_SEARCHED = "web_searched"
    CALENDAR_EVENT_CREATED = "calendar_event_created"
    SKILL_LOADED = "skill_loaded"
    BADGE_UNLOCKED = "badge_unlocked"
    LEVEL_UP = "level_up"
    XP_EARNED = "xp_earned"
    REWARD_GRANTED = "reward_granted"
    MEMORY_MILESTONE = "memory_milestone"
    QUEST_COMPLETED = "quest_completed"
    REFERRAL_COMPLETED = "referral_completed"
    PACT_VIOLATED = "pact_violated"
    ONBOARDING_COMPLETED = "onboarding_completed"


class GameEvent(BaseModel):
    """Canonical domain event envelope."""
    event: GameEventType
    user_id: int  # User.id (DB PK, not tg_user_id)
    feature_id: str  # e.g. "F001"
    properties: dict = {}
    timestamp: datetime


# ─── XP & Leveling ───────────────────────────────────────────────
class XPAction(str, Enum):
    HABIT_LOGGED = "habit_logged"
    DAILY_LOGIN = "daily_login"
    PLAN_CREATED = "plan_created"
    CHALLENGE_COMPLETED = "challenge_completed"
    FEATURE_FIRST_USE = "feature_first_use"
    CODE_EXECUTED = "code_executed"
    WEB_SEARCHED = "web_searched"


class UserLevel(str, Enum):
    BEGINNER = "Beginner"
    PLANNER = "Planner"
    STRATEGIST = "Strategist"
    MASTER = "Master"
    SAGE = "Sage"


LEVEL_THRESHOLDS: dict[UserLevel, int] = {
    UserLevel.BEGINNER: 0,
    UserLevel.PLANNER: 100,
    UserLevel.STRATEGIST: 500,
    UserLevel.MASTER: 1500,
    UserLevel.SAGE: 5000,
}

XP_AMOUNTS: dict[XPAction, int] = {
    XPAction.HABIT_LOGGED: 10,
    XPAction.DAILY_LOGIN: 5,
    XPAction.PLAN_CREATED: 15,
    XPAction.CHALLENGE_COMPLETED: 25,
    XPAction.FEATURE_FIRST_USE: 20,
    XPAction.CODE_EXECUTED: 5,
    XPAction.WEB_SEARCHED: 3,
}

# Anti-abuse: max XP earnable per action type per calendar day.
XP_DAILY_CAPS: dict[XPAction, int] = {
    XPAction.HABIT_LOGGED: 100,
    XPAction.DAILY_LOGIN: 5,
    XPAction.PLAN_CREATED: 45,
    XPAction.CHALLENGE_COMPLETED: 25,
    XPAction.FEATURE_FIRST_USE: 60,
    XPAction.CODE_EXECUTED: 25,
    XPAction.WEB_SEARCHED: 15,
}


# ─── Badges ──────────────────────────────────────────────────────
class BadgeCategory(str, Enum):
    ACTION = "action"
    MILESTONE = "milestone"
    SOCIAL = "social"
    SECRET = "secret"


class BadgeDefinition(BaseModel):
    """Data-driven badge template (no code deploys to add a new badge)."""
    badge_id: str
    name: str
    description: str
    category: BadgeCategory
    icon: str  # emoji
    target_count: int
    event_type: GameEventType
    event_filter: dict = {}
    secret: bool = False


# ─── Variable Rewards ────────────────────────────────────────────
class RewardTier(str, Enum):
    COMMON = "common"
    RARE = "rare"
    EPIC = "epic"


class RewardType(str, Enum):
    BONUS_XP = "bonus_xp"
    STREAK_FREEZE = "streak_freeze"
    BADGE_HINT = "badge_hint"
    PERSONA_UNLOCK = "persona_unlock"


REWARD_PROBABILITIES: dict[RewardTier, float] = {
    RewardTier.COMMON: 0.60,
    RewardTier.RARE: 0.30,
    RewardTier.EPIC: 0.10,
}

# Pity timer: guaranteed non-common drop after this many consecutive commons.
PITY_TIMER_THRESHOLD: int = 10


# ─── Streaks ─────────────────────────────────────────────────────
STREAK_FREEZE_AWARD_INTERVAL: int = 7   # earn 1 freeze every 7-day streak
STREAK_FREEZE_MAX: int = 2              # max stored freeze tokens
STREAK_MILESTONES: list[int] = [7, 30, 100, 365]


# ─── Memory milestones ───────────────────────────────────────────
MEMORY_MILESTONES: list[int] = [10, 50, 100, 500, 1000]


# ─── Skill Tree categories ───────────────────────────────────────
class SkillCategory(str, Enum):
    PRODUCTIVITY = "productivity"
    HABITS = "habits"
    SELF_KNOWLEDGE = "self_knowledge"
    TOOL_MASTERY = "tool_mastery"


# Maps game events → skill category for auto-routing XP.
EVENT_TO_SKILL: dict[GameEventType, SkillCategory] = {
    GameEventType.PLAN_CREATED: SkillCategory.PRODUCTIVITY,
    GameEventType.HABIT_LOGGED: SkillCategory.HABITS,
    GameEventType.STREAK_MILESTONE: SkillCategory.HABITS,
    GameEventType.MESSAGE_SENT: SkillCategory.SELF_KNOWLEDGE,
    GameEventType.CODE_EXECUTED: SkillCategory.TOOL_MASTERY,
    GameEventType.WEB_SEARCHED: SkillCategory.TOOL_MASTERY,
    GameEventType.CALENDAR_EVENT_CREATED: SkillCategory.TOOL_MASTERY,
    GameEventType.SKILL_LOADED: SkillCategory.TOOL_MASTERY,
}


# ─── Feature Flags (all False = dark launch) ─────────────────────
FEATURE_FLAG_DEFAULTS: dict[str, bool] = {
    "F001_XP_ENGINE": False,
    "F002_EVENT_BUS": False,
    "F003_BADGES": False,
    "F004_VARIABLE_REWARDS": False,
    "F005_LEADERBOARD": False,
    "F006_STREAKS": False,
    "F007_MEMORY_MILESTONES": False,
    "F008_ONBOARDING_QUICK_WIN": False,
    "F009_MEMORY_REVEAL": False,
    "F010_CONTEXTUAL_UPGRADE": False,
    "F011_BREAK_ENHANCED": False,
    "F012_WEEKLY_SCORECARD": False,
    "F013_INSIGHT_CARDS": False,
    "F014_ADAPTIVE_TONE": False,
    "F015_MORNING_CHALLENGES": False,
    "F016_TIME_CAPSULE": False,
    "F017_HABIT_STACKING": False,
    "F018_REFERRAL": False,
    "F019_PREMIUM_TASTE": False,
    "F020_LIFE_STORY": False,
    "F021_ACCOUNTABILITY_PACT": False,
    "F022_SKILL_TREE": False,
    "F023_GROUP_CIRCLES": False,
    "F024_GROWTH_QUEST": False,
    "F025_MEMORY_COLLECTION": False,
    "F026_PERSONA_CUSTOMIZATION": False,
    "F027_EASTER_EGGS": False,
    "F028_MEMORY_DECAY_WARNING": False,
    "F029_TEACH_MOTIVI": False,
}

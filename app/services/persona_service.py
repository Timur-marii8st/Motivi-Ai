"""Persona Customization — system prompt modifier based on user preferences.

Premium users can set tone, emoji density, and response length.
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.settings_service import SettingsService


async def get_persona_prompt_modifier(
    session: AsyncSession, user_id: int
) -> str:
    """Build a system prompt modifier from user persona preferences.

    Returns an empty string if feature disabled or no preferences set.
    """
    if not settings.is_feature_enabled("F026_PERSONA_CUSTOMIZATION"):
        return ""

    try:
        user_settings = await SettingsService.get_or_create(session, user_id)
        prefs = user_settings.persona_preferences_json
        if not prefs:
            return ""

        parts = []
        if "tone" in prefs:
            parts.append(f"Communication tone: {prefs['tone']}")
        if "emoji_density" in prefs:
            density_map = {
                "low": "Minimal emoji usage",
                "medium": "Moderate emoji usage",
                "high": "Generous emoji usage",
            }
            parts.append(density_map.get(prefs["emoji_density"], ""))
        if "response_length" in prefs:
            length_map = {
                "concise": "Keep responses brief and to the point",
                "detailed": "Provide thorough, detailed responses",
            }
            parts.append(length_map.get(prefs["response_length"], ""))

        parts = [p for p in parts if p]
        if not parts:
            return ""
        return "\n<PersonaPreferences>\n" + ". ".join(parts) + ".\n</PersonaPreferences>"
    except Exception:
        logger.exception("Failed to get persona modifier for user {}", user_id)
        return ""

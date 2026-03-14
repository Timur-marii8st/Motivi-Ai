"""Life Story router — /story command for narrative summary."""
from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.types import Message
from loguru import logger

from ...config import settings
from ...services.profile_services import get_or_create_user
from ...services.proactive_flows import ProactiveFlows

router = Router(name="story")


@router.message(F.text == "/story")
async def story_cmd(message: Message, session):
    """Generate a life narrative summary from accumulated memories."""
    if not settings.is_feature_enabled("F020_LIFE_STORY"):
        await message.answer("This feature is not yet available.")
        return

    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    # Check 30-day minimum
    days_used = (datetime.now(timezone.utc) - user.created_at).days
    if days_used < 30:
        await message.answer(
            f"📖 Your life story will unlock after <b>30 days</b> of use.\n"
            f"You're on day <b>{days_used}</b> — keep going! "
            f"Every conversation adds to your story."
        )
        return

    thinking = await message.answer("📖 Crafting your story... this takes a moment.")

    try:
        prompt = (
            "You are a narrative writer. Using everything you know about me "
            "from my memories, facts, habits, and episodes, write a compelling "
            "'life chapter' covering my journey with Motivi. Include:\n"
            "- Goals I've set and progress made\n"
            "- Habits I've formed or am working on\n"
            "- Challenges I've overcome\n"
            "- Growth areas and patterns you've noticed\n\n"
            "Write in second person ('You started...'). "
            "Keep it warm, encouraging, and authentic. 3-5 paragraphs. "
            "Use HTML formatting for emphasis."
        )

        flows = ProactiveFlows(session)
        await flows._run_flow(
            user=user,
            prompt=prompt,
            greeting="📖 <b>Your Life Story — A Chapter</b>",
            top_k=20,
        )
        logger.info("Life story generated for user {}", user.id)

    except Exception:
        logger.exception("Failed to generate story for user {}", user.id)
        await message.answer(
            "Sorry, I couldn't generate your story right now. Try again later."
        )
    finally:
        try:
            await thinking.delete()
        except Exception:
            pass

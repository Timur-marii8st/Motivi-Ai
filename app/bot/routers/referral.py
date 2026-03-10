"""Referral system router — /referral command and deep-link handling."""
from __future__ import annotations

import html
import secrets
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.types import Message
from loguru import logger

from ...config import settings
from ...services.profile_services import get_or_create_user
from ...services.event_bus import event_bus
from ...services.gamification.schemas import GameEvent, GameEventType

router = Router(name="referral")


@router.message(F.text == "/referral")
async def referral_cmd(message: Message, session):
    """Generate and display the user's referral link."""
    if not settings.is_feature_enabled("F018_REFERRAL"):
        await message.answer("This feature is not yet available.")
        return

    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    # Generate referral code if not exists
    if not user.referral_code:
        user.referral_code = secrets.token_urlsafe(16)[:12]
        user.touch()
        session.add(user)
        await session.commit()

    # Get bot username
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties

    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    try:
        bot_info = await bot.get_me()
        bot_username = bot_info.username
    finally:
        await bot.session.close()

    link = f"https://t.me/{bot_username}?start=ref_{user.referral_code}"
    days_used = (datetime.now(timezone.utc) - user.created_at).days

    share_text = (
        f"I've been using Motivi as my AI planning assistant for {days_used} days. "
        f"It remembers everything about my goals and keeps me on track. "
        f"Try it with an extended 14-day trial: {link}"
    )

    await message.answer(
        f"🔗 <b>Your Referral Link</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"Share this with friends:\n"
        f"<i>{html.escape(share_text)}</i>\n\n"
        f"📌 When a friend signs up:\n"
        f"  • They get a <b>14-day trial</b> (instead of 7)\n"
        f"  • You get <b>7 bonus days</b> added to your subscription"
    )


async def handle_referral_deep_link(
    session,
    referral_code: str,
    new_user_id: int,
) -> None:
    """Process a referral deep link during onboarding.

    Called from onboarding.py when /start ref_XXXXX is detected.
    """
    if not settings.is_feature_enabled("F018_REFERRAL"):
        return

    from ...models.users import User
    from sqlmodel import select

    try:
        # Find referrer
        result = await session.execute(
            select(User).where(User.referral_code == referral_code)
        )
        referrer = result.scalar_one_or_none()
        if not referrer:
            logger.warning("Referral code '{}' not found", referral_code)
            return

        # Get new user
        new_user = await session.get(User, new_user_id)
        if not new_user:
            return

        # Don't self-refer
        if referrer.id == new_user.id:
            return

        # Mark referral
        new_user.referred_by = referrer.id
        new_user.touch()
        session.add(new_user)

        # Extend new user's trial by 7 days (total 14)
        # Trial is implicit (created_at + TRIAL_DAYS), so we set a subscription
        new_trial_end = new_user.created_at + timedelta(
            days=settings.TRIAL_DAYS + 7
        )
        new_user.subscription_ends_at = new_trial_end

        # Extend referrer's subscription by 7 days
        now = datetime.now(timezone.utc)
        if referrer.subscription_ends_at and referrer.subscription_ends_at > now:
            referrer.subscription_ends_at += timedelta(days=7)
        elif referrer.is_trial:
            # Give them premium until their trial end + 7 days
            trial_end = referrer.created_at + timedelta(days=settings.TRIAL_DAYS)
            referrer.subscription_ends_at = trial_end + timedelta(days=7)
        else:
            # Expired user — give them 7 days from now
            referrer.subscription_ends_at = now + timedelta(days=7)
        referrer.touch()
        session.add(referrer)

        await session.flush()

        logger.info(
            "Referral processed: user {} referred user {} (code={})",
            referrer.id,
            new_user.id,
            referral_code,
        )

        await event_bus.emit(
            GameEvent(
                event=GameEventType.REFERRAL_COMPLETED,
                user_id=referrer.id,
                feature_id="F018",
                properties={"referred_user_id": new_user.id},
                timestamp=datetime.now(timezone.utc),
            )
        )
    except Exception:
        logger.exception("Failed to process referral code '{}'", referral_code)

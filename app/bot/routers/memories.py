"""Memory Collection & Teach Motivi routers.

/my_memories — shows categorized memory collection
/correct — lets users review and delete incorrect facts
"""
from __future__ import annotations

import html as html_mod
from collections import defaultdict

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger
from sqlalchemy import func
from sqlmodel import select

from ...config import settings
from ...models.core_memory import CoreFact, CoreMemory, CoreFactEmbedding
from ...services.profile_services import get_or_create_user

router = Router(name="memories")

# Category icons
_CAT_ICONS: dict[str, str] = {
    "career": "🏢",
    "health": "💪",
    "interests": "🎯",
    "goals": "🎯",
    "education": "📚",
    "relationships": "👥",
    "habits": "🔄",
    "personality": "🧠",
    "preferences": "⚙️",
}


@router.message(F.text == "/my_memories")
async def my_memories_cmd(message: Message, session):
    """Display the user's memory collection with categorized counts."""
    if not settings.is_feature_enabled("F025_MEMORY_COLLECTION"):
        await message.answer("This feature is not yet available.")
        return

    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    cm_result = await session.execute(
        select(CoreMemory.id).where(CoreMemory.user_id == user.id)
    )
    cm_id = cm_result.scalar_one_or_none()

    if not cm_id:
        await message.answer(
            "📚 Your memory collection is empty! "
            "Start chatting with me and I'll learn about you."
        )
        return

    # Get all facts grouped by category
    facts_result = await session.execute(
        select(CoreFact.category, func.count())
        .where(CoreFact.core_memory_id == cm_id)
        .group_by(CoreFact.category)
    )
    categories = facts_result.all()

    total = sum(count for _, count in categories)
    if total == 0:
        await message.answer(
            "📚 Your memory collection is empty! "
            "Start chatting with me and I'll learn about you."
        )
        return

    lines = [f"📚 <b>Your Memory Collection</b>\n"]
    lines.append(f"Total: <b>{total}</b> memories\n")

    for category, count in sorted(categories, key=lambda x: -x[1]):
        cat_name = (category or "uncategorized").lower()
        icon = _CAT_ICONS.get(cat_name, "📝")
        display_name = (category or "Uncategorized").title()
        lines.append(f"{icon} {display_name}: <b>{count}</b>")

    lines.append(
        "\n💡 Use /correct to review and fix what I know about you."
    )

    await message.answer("\n".join(lines))


@router.message(F.text == "/correct")
async def correct_cmd(message: Message, session):
    """List recent core facts with delete buttons."""
    if not settings.is_feature_enabled("F029_TEACH_MOTIVI"):
        await message.answer("This feature is not yet available.")
        return

    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    cm_result = await session.execute(
        select(CoreMemory.id).where(CoreMemory.user_id == user.id)
    )
    cm_id = cm_result.scalar_one_or_none()

    if not cm_id:
        await message.answer("I don't have any facts about you yet!")
        return

    facts_result = await session.execute(
        select(CoreFact)
        .where(CoreFact.core_memory_id == cm_id)
        .order_by(CoreFact.created_at.desc())
        .limit(10)
    )
    facts = facts_result.scalars().all()

    if not facts:
        await message.answer("I don't have any facts about you yet!")
        return

    await message.answer(
        "🧠 <b>Here's what I know about you.</b>\n"
        "Tap ❌ to remove anything incorrect:"
    )

    for fact in facts:
        text = html_mod.escape(fact.fact_text[:200])
        cat = f" [{fact.category}]" if fact.category else ""
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ Remove",
                        callback_data=f"delete_fact:{fact.id}",
                    )
                ]
            ]
        )
        await message.answer(f"• {text}{cat}", reply_markup=keyboard)


@router.callback_query(F.data.startswith("delete_fact:"))
async def delete_fact_callback(callback: CallbackQuery, session):
    """Delete a core fact and its embedding."""
    fact_id = int(callback.data.split(":")[1])
    user = await get_or_create_user(
        session, callback.from_user.id, callback.message.chat.id
    )

    fact = await session.get(CoreFact, fact_id)
    if not fact:
        await callback.answer("Fact not found.", show_alert=True)
        return

    # Verify ownership
    cm_result = await session.execute(
        select(CoreMemory.id).where(
            CoreMemory.id == fact.core_memory_id,
            CoreMemory.user_id == user.id,
        )
    )
    if not cm_result.scalar_one_or_none():
        await callback.answer("Access denied.", show_alert=True)
        return

    # Delete embedding first
    emb_result = await session.execute(
        select(CoreFactEmbedding).where(
            CoreFactEmbedding.core_fact_id == fact_id
        )
    )
    emb = emb_result.scalar_one_or_none()
    if emb:
        await session.delete(emb)

    await session.delete(fact)
    await session.commit()

    await callback.answer("✅ Fact removed!")
    await callback.message.edit_text(
        f"<s>{callback.message.text}</s>\n<i>Removed</i>",
        reply_markup=None,
    )
    logger.info("User {} deleted fact {}", user.id, fact_id)

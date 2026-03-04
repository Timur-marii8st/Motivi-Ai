"""
app/bot/routers/group.py
Handles Motivi_AI behaviour inside Telegram group/supergroup chats.

Strategy:
  • The bot responds only when it is explicitly addressed:
      1. A user mentions the bot by @username
      2. A user replies directly to one of the bot's messages
      3. A user sends a command (handled by the existing command routers)
  • All other messages in the group are silently ignored — the bot does not
    eavesdrop on conversations between members.
  • Group messages are always tied to the Telegram user who sent them, so
    the full per-user memory / subscription logic still applies.
  • Groups themselves are NOT stored; we use the sender's personal chat_id
    for memory and history (DM-first approach).  The response is sent back
    into the group, but context is private per user.
"""
from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from loguru import logger

from ...config import settings
from ...services.profile_services import get_or_create_user
from ...services.episodic_memory_service import EpisodicMemoryService
from ...services.core_memory_service import CoreMemoryService
from ...services.working_memory_service import WorkingMemoryService
from ...services.memory_orchestrator import MemoryOrchestrator
from ...llm.conversation_service import ConversationService
from ...services.extractor_service import ExtractorService
from ...embeddings.gemini_embedding_client import GeminiEmbeddings
from ...services.tool_executor import ToolExecutor
from ...services.conversation_history_service import ConversationHistoryService
from ...services.fact_cleanup_service import FactCleanupService
from ...utils.get_user_time import get_time_in_zone

router = Router(name="group")

# Module-level singletons (same as in chat.py — these are stateless services)
_gemini_embeddings = GeminiEmbeddings()
_episodic_service = EpisodicMemoryService(_gemini_embeddings)
_core_service = CoreMemoryService(_gemini_embeddings)
_working_service = WorkingMemoryService(_gemini_embeddings)
_memory_orchestrator = MemoryOrchestrator(_episodic_service, _core_service, _working_service)
_conversation_service = ConversationService()
_extractor_service = ExtractorService()
_fact_cleanup_service = FactCleanupService()


def _is_group_message(message: Message) -> bool:
    """Return True if the message originates from a group or supergroup."""
    return message.chat.type in ("group", "supergroup")


async def _bot_is_mentioned(message: Message, bot: Bot) -> bool:
    """
    Return True if the bot is explicitly addressed in this group message.

    Addressed = any of:
      - Message replies directly to a bot message
      - Message text contains @bot_username
      - Message caption contains @bot_username (for photos/docs with captions)
    """
    me = await bot.get_me()
    bot_username = (me.username or "").lower()

    # Check if this is a reply to one of the bot's own messages
    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.id == me.id:
            return True

    # Check for @mention in text or caption
    text = message.text or message.caption or ""
    if bot_username and f"@{bot_username}".lower() in text.lower():
        return True

    # Check entities for explicit mentions
    entities = message.entities or message.caption_entities or []
    for entity in entities:
        if entity.type == "mention":
            mention_text = text[entity.offset : entity.offset + entity.length]
            if mention_text.lstrip("@").lower() == bot_username:
                return True

    return False


def _strip_bot_mention(text: str, bot_username: str) -> str:
    """Remove the @bot_username mention from the user message before processing."""
    import re
    return re.sub(rf"@{re.escape(bot_username)}\s*", "", text, flags=re.IGNORECASE).strip()


# --- Handler ---

@router.message()
async def handle_group_message(message: Message, session, bot: Bot):
    """
    Entry point for all group/supergroup text messages.

    Only fires when the bot is mentioned or the user replies to the bot;
    all other messages fall through silently.
    """
    if not _is_group_message(message):
        # Not a group message — let the private-chat routers handle it
        return

    if not message.text:
        # Ignore non-text messages in groups (voice/photos handled separately in multimodal.py)
        return

    if not await _bot_is_mentioned(message, bot):
        # Not addressed to us — ignore silently
        return

    # --- User lookup ---
    sender = message.from_user
    if not sender:
        return

    user = await get_or_create_user(session, sender.id, message.chat.id)
    if not user.name:
        await message.reply(
            "Привет! Чтобы я мог помочь, сначала настрой профиль в личном чате со мной — нажми /start там."
        )
        return

    # Strip @mention from the text so the LLM doesn't see it
    me = await bot.get_me()
    user_text = _strip_bot_mention(message.text, me.username or "")
    if not user_text:
        await message.reply("Как я могу помочь?")
        return

    # --- "Thinking" indicator ---
    thinking_msg = None
    try:
        thinking_msg = await message.reply("Дай мне подумать...")
    except Exception:
        pass

    try:
        # Use user's personal chat_id for history/memory (DM-first approach)
        personal_chat_id = user.tg_chat_id
        history = await ConversationHistoryService.get_history(personal_chat_id)

        try:
            memory_pack = await _memory_orchestrator.assemble(session, user, user_text, top_k=5)
        except Exception as e:
            logger.error("Memory assembly failed for group user {}: {}", user.id, e)
            await message.reply("Извини, не могу вспомнить контекст прямо сейчас. Попробуй ещё раз.")
            return

        tool_executor = ToolExecutor(session, bot=bot)

        # Add current time context (same pattern as private chat handler)
        try:
            user_time = get_time_in_zone(user.user_timezone)
        except Exception:
            from datetime import datetime, timezone
            user_time = datetime.now(timezone.utc).isoformat()

        time_block = f"<KnowledgeBase>Current time: {user_time}\nContext: Group chat ({message.chat.title or message.chat.id})</KnowledgeBase>"
        enriched_text = f"{user_text}\n\n{time_block}"

        reply, updated_history = await _conversation_service.respond_with_tools(
            enriched_text,
            memory_pack,
            personal_chat_id,
            tool_executor,
            session,
            conversation_history=history,
        )

        # Reply in the group (not the user's DM)
        await message.reply(reply)

        # Persist history to user's personal context
        await ConversationHistoryService.save_history(personal_chat_id, updated_history)

        # Background: extract facts and clean duplicates (non-fatal)
        try:
            info_text = f"User message: {user_text}\nAI Assistant message: {reply}"
            await _extractor_service.find_write_important_info(user.id, session, info_text)
        except Exception as e:
            logger.exception("Fact extraction failed for group user {}: {}", user.id, e)

        try:
            await _fact_cleanup_service.clear_duplicate_facts(session, user.id)
        except Exception as e:
            logger.exception("Fact cleanup failed for group user {}: {}", user.id, e)

    finally:
        if thinking_msg:
            try:
                await thinking_msg.delete()
            except Exception:
                pass

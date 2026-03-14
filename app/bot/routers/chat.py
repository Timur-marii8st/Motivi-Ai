from __future__ import annotations
import re
from aiogram import Router, F
from aiogram.types import Message
from loguru import logger

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
from ...services.settings_service import SettingsService
from ...utils.get_user_time import get_time_in_zone


router = Router(name="chat")

# ── Search token detection ──────────────────────────────────────────────────
# Supported formats:
#   !!<query>           — ultra-short (e.g.  !!bitcoin price)
#   !search <query>     — explicit English trigger
#   !поиск <query>      — explicit Russian trigger
_SEARCH_PATTERNS = [
    re.compile(r"^!!\s*(.+)", re.DOTALL),
    re.compile(r"^!search\s+(.+)", re.DOTALL | re.IGNORECASE),
    re.compile(r"^!поиск\s+(.+)", re.DOTALL | re.IGNORECASE),
]

def _extract_search_query(text: str) -> str | None:
    """Return the search query if the message starts with a search token, else None."""
    stripped = text.strip()
    for pattern in _SEARCH_PATTERNS:
        m = pattern.match(stripped)
        if m:
            return m.group(1).strip()
    return None

extractor_service = ExtractorService()
gemini_embeddings = GeminiEmbeddings()
episodic_service = EpisodicMemoryService(gemini_embeddings)
core_service = CoreMemoryService(gemini_embeddings)
working_service = WorkingMemoryService(gemini_embeddings)
memory_orchestrator = MemoryOrchestrator(episodic_service, core_service, working_service)
conversation_service = ConversationService()
fact_cleanup_service = FactCleanupService()


@router.message(F.text & ~F.text.startswith("/"))
async def handle_chat(message: Message, session):
    """
    Natural conversation with Motivi, using full memory context.
    """
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    if not user.name:
        await message.answer("Давай сначала настроим твой профиль! Нажми /start, чтобы начать.")
        return

    user_text = message.text.strip()

    # ── Search token handling ──────────────────────────────────────────
    # Detect !! / !search / !поиск prefix and inject a mandatory search
    # instruction so the LLM calls web_search as its very first action.
    search_query = _extract_search_query(user_text)
    forced_tool_choice = None
    if search_query:
        # Strip the token so the LLM doesn't see the raw !! syntax
        user_text = search_query
        # Append a directive the LLM will read in the system context block
        user_text = (
            f"{search_query}\n\n"
            "<SearchDirective>The user has explicitly requested a web search. "
            "You MUST call the web_search tool immediately with the query above "
            "before composing your reply. Do not skip this step.</SearchDirective>"
        )
        forced_tool_choice = {"type": "function", "function": {"name": "web_search"}}
        logger.info("Search token detected for user {}; query='{}'", user.id, search_query)

    # Send an immediate "thinking" message and keep reference so we can delete it later
    thinking_message = None
    try:
        thinking_message = await message.answer("Дай мне подумать...")
    except Exception as e:
        logger.warning("Failed to send thinking message for user {}: {}", user.id, e)

    try:
        # Retrieve conversation history
        history = await ConversationHistoryService.get_history(user.tg_chat_id)

        # Assemble memory context
        try:
            memory_pack = await memory_orchestrator.assemble(session, user, user_text, top_k=5)
        except Exception as e:
            logger.error("Memory assembly failed for user {}: {}", user.id, e)
            await message.answer("Извини, мне сложно вспомнить нашу историю прямо сейчас. Давай попробуем чуть позже.")
            return
        
        tool_executor = ToolExecutor(session, bot=message.bot)

        # Get current time in user's timezone (or UTC if not set)
        try:
            user_time = get_time_in_zone(user.user_timezone)
        except Exception as e:
            logger.warning("Failed to get time in zone for user {}: {}", user.id, e)
            # Fallback to UTC time
            from datetime import datetime, timezone as _tz
            user_time = datetime.now(_tz.utc).isoformat()

        time_block = f"<KnowledgeBase>Current time: {user_time}</KnowledgeBase>"
        user_text = f"{user_text}\n\n{time_block}"

        # Resolve user language preference
        language = "ru"
        try:
            user_settings = await SettingsService.get_or_create(session, user.id)
            language = (user_settings.summary_preferences_json or {}).get("language", "ru")
        except Exception as e:
            logger.warning("Failed to load user settings for language for user {}: {}", user.id, e)

        # Generate response and get updated history
        reply, updated_history = await conversation_service.respond_with_tools(
            user_text,
            memory_pack,
            user.tg_chat_id,
            tool_executor,
            session,
            conversation_history=history,
            language=language,
            forced_tool_choice=forced_tool_choice,
        )

        await message.answer(reply)

        # Save the updated history back to Redis
        await ConversationHistoryService.save_history(user.tg_chat_id, updated_history)

        try:
            info_text = f"User message: {user_text}\nAI Assistant message: {reply}"
            has_important_info = await extractor_service.find_write_important_info(user.id, session, info_text)
            logger.info("Important info extraction for user {}: {}", user.id, has_important_info)
        except Exception as e:
            logger.exception("Failed to store episode for user {}: {}", user.id, e)

        # ── Post-message gamification (streaks, milestones, XP) ──
        try:
            from ...services.post_message_handler import handle_post_message_gamification
            await handle_post_message_gamification(session, user, message.chat.id)
        except Exception as e:
            logger.exception("Post-message gamification failed for user {}: {}", user.id, e)

        try:
            await fact_cleanup_service.clear_duplicate_facts(session, user.id)
            logger.info("Cleared duplicate facts for user {}", user.id)
        except ValueError as e:
            if "The truth value of an array with more than one element is ambiguous" in str(e):
                logger.error(f"Numpy array truth value error in clear_duplicate_facts for user {user.id}: {e}")
            else:
                logger.exception("Failed to clear duplicate facts for user {}: {}", user.id, e)
        except Exception as e:
            logger.exception("Failed to clear duplicate facts for user {}: {}", user.id, e)
    
    finally:
        # Always remove the thinking message, even if an error occurred
        if thinking_message:
            try:
                await thinking_message.delete()
            except Exception as e:
                logger.warning("Failed to delete thinking message for user {}: {}", user.id, e)

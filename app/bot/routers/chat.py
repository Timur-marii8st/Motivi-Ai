from __future__ import annotations
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
from ...mcp_client.client import MCPClient
from ...config import settings
from ...services.conversation_history_service import ConversationHistoryService
from ...services.fact_cleanup_service import FactCleanupService
from ...utils.get_user_time import get_time_in_zone


router = Router(name="chat")

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
        # Перевод: Предложение начать регистрацию
        await message.answer("Давай сначала настроим твой профиль! Нажми /start, чтобы начать.")
        return

    user_text = message.text.strip()

    # Retrieve conversation history
    history = await ConversationHistoryService.get_history(user.tg_chat_id)

    # Assemble memory context
    try:
        memory_pack = await memory_orchestrator.assemble(session, user, user_text, top_k=5)
    except Exception as e:
        logger.error("Memory assembly failed for user {}: {}", user.id, e)
        # Перевод: Сообщение об ошибке памяти
        await message.answer("Извини, мне сложно вспомнить нашу историю прямо сейчас. Давай попробуем чуть позже.")
        return
    
    mcp_client = MCPClient(settings.MCP_BASE_URL, settings.MCP_SECRET_TOKEN)
    tool_executor = ToolExecutor(session, mcp_client)

    # Get current time in user's timezone (or UTC if not set)
    try:
        user_time = get_time_in_zone(user.user_timezone)
    except Exception as e:
        logger.warning("Failed to get time in zone for user {}: {}", user.id, e)
        # Fallback to UTC time
        from datetime import datetime, timezone
        user_time = datetime.now(timezone.utc).isoformat()
        
    time_block = f"<KnowledgeBase>Current time: {user_time}</KnowledgeBase>"
    user_text = f"{user_text}\n\n{time_block}"

    # Generate response and get updated history
    reply, updated_history = await conversation_service.respond_with_tools(
        user_text,
        memory_pack,
        user.tg_chat_id,
        tool_executor,
        session,
        conversation_history=history,
    )

    await message.answer(reply)

    # Save the updated history back to Redis
    await ConversationHistoryService.save_history(user.tg_chat_id, updated_history)

    try:
        info_text = f"User message: {user_text}\nAI Assistant message: {reply}"
        has_important_info = await extractor_service.find_write_important_info(user.id, session, info_text)
        logger.info("Important info extraction for user {}: {}", user.id, has_important_info)
    except Exception as e:
        logger.exception("Failed to store episode for user %s: %s", user.id, e)

    try:
        await fact_cleanup_service.clear_duplicate_facts(session, user.id)
        logger.info("Cleared duplicate facts for user {}", user.id)
    except ValueError as e:
        if "The truth value of an array with more than one element is ambiguous" in str(e):
            logger.error(f"Numpy array truth value error in clear_duplicate_facts for user {user.id}: {e}")
        else:
            logger.exception("Failed to clear duplicate facts for user %s: %s", user.id, e)
    except Exception as e:
        logger.exception("Failed to clear duplicate facts for user %s: %s", user.id, e)
from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from loguru import logger

from ...services.profile_services import get_or_create_user
from ...services.episodic_memory_service import EpisodicMemoryService
from ...services.memory_orchestrator import MemoryOrchestrator
from ...llm.conversation_service import ConversationService
from ...embeddings.gemini_embedding_client import GeminiEmbeddings
from ...services.tool_executor import ToolExecutor
from ...mcp_client.client import MCPClient
from ...config import settings
from ...services.conversation_history_service import ConversationHistoryService

router = Router(name="chat")

gemini_embeddings = GeminiEmbeddings()
episodic_service = EpisodicMemoryService(gemini_embeddings)
memory_orchestrator = MemoryOrchestrator(episodic_service)
conversation_service = ConversationService()


@router.message(F.text & ~F.text.startswith("/"))
async def handle_chat(message: Message, session):
    """
    Natural conversation with Moti, using full memory context.
    """
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    if not user.name:
        await message.answer("Let's start by setting up your profile! Use /start to begin.")
        return

    user_text = message.text.strip()

    # Retrieve conversation history
    history = await ConversationHistoryService.get_history(user.tg_chat_id)

    # Assemble memory context
    try:
        memory_pack = await memory_orchestrator.assemble(session, user, user_text, top_k=5)
    except Exception as e:
        logger.error("Memory assembly failed for user {}: {}", user.id, e)
        await message.answer("Sorry, I'm having trouble recalling our history. Let me try again later.")
        return
    
    mcp_client = MCPClient(settings.MCP_BASE_URL, settings.MCP_SECRET_TOKEN)
    tool_executor = ToolExecutor(session, mcp_client)

    # Generate response and get updated history
    reply, updated_history = await conversation_service.respond_with_tools(
        user_text,
        memory_pack,
        user.tg_chat_id,
        tool_executor,
        session,
        conversation_history=history
    )

    await message.answer(reply)

    # Save the updated history back to Redis
    await ConversationHistoryService.save_history(user.tg_chat_id, updated_history)

    # Optionally: store this interaction as an episode (do selectively; not every message)
    # We'll store when the user message likely describes a completed task or notable event.
    try:
        lower_text = user_text.lower()
        keywords = ("completed", "done", "finished", "achieved", "created", "submitted")
        if any(kw in lower_text for kw in keywords) and len(user_text) > 10:
            metadata = {"tg_message_id": message.message_id, "chat_id": message.chat.id}
            await episodic_service.store_episode(session, user.id, "chat_interaction", user_text, metadata)
    except Exception as e:
        logger.exception("Failed to store episode for user %s: %s", user.id, e)
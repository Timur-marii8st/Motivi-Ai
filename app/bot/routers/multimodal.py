from __future__ import annotations
import tempfile
from aiogram import Router, F
from aiogram.types import Message, Voice, PhotoSize
from loguru import logger

from ...services.profile_services import get_or_create_user
from ...services.stt_service import transcribe_voice
from ...services.vision_service import analyze_photo
from ...llm.conversation_service import ConversationService
from ...services.memory_orchestrator import MemoryOrchestrator
from ...services.episodic_memory_service import EpisodicMemoryService
from ...services.core_memory_service import CoreMemoryService
from ...services.working_memory_service import WorkingMemoryService
from ...embeddings.gemini_embedding_client import GeminiEmbeddings
from ...mcp_client.client import MCPClient
from ...services.tool_executor import ToolExecutor
from ...config import settings
from ...services.conversation_history_service import ConversationHistoryService

router = Router(name="multimodal")

# Singletons
gemini_embeddings = GeminiEmbeddings()
episodic_service = EpisodicMemoryService(gemini_embeddings)
core_service = CoreMemoryService(gemini_embeddings)
working_service = WorkingMemoryService(gemini_embeddings)
memory_orchestrator = MemoryOrchestrator(episodic_service, core_service, working_service)
conversation_service = ConversationService()


@router.message(F.voice)
async def handle_voice(message: Message, session):
    """Handle voice messages with STT."""
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    
    if not user.name:
        await message.answer("Please complete onboarding first: /start")
        return
    
    await message.answer("🎤 Transcribing...")
    
    # Download and process voice in a secure temporary file
    voice: Voice = message.voice
    file = await message.bot.get_file(voice.file_id)
    
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg") as tmp:
            await message.bot.download_file(file.file_path, tmp.name)
            transcript = await transcribe_voice(tmp.name)
            
            if not transcript:
                await message.answer("Sorry, I couldn't understand that. Try again?")
                return
            
            await message.answer(f"💬 You said: <i>{transcript}</i>")
            
            # Retrieve conversation history
            history = await ConversationHistoryService.get_history(user.tg_chat_id)
            
            # Process as text
            memory_pack = await memory_orchestrator.assemble(session, user, transcript, top_k=5)
            
            mcp_client = MCPClient(settings.MCP_BASE_URL, settings.MCP_SECRET_TOKEN)
            tool_executor = ToolExecutor(session, mcp_client)
            
            response, updated_history = await conversation_service.respond_with_tools(
                transcript,
                memory_pack,
                user.tg_chat_id,
                tool_executor,
                session,
                conversation_history=history
            )
            
            await message.answer(response)
            
            # Save the updated history
            await ConversationHistoryService.save_history(user.tg_chat_id, updated_history)
    
    except Exception as e:
        logger.exception("Voice processing failed: {}", e)
        await message.answer("Oops, something went wrong processing your voice message.")


@router.message(F.photo)
async def handle_photo(message: Message, session):
    """Handle photos with Vision Gemini."""
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    
    if not user.name:
        await message.answer("Please complete onboarding first: /start")
        return
    
    await message.answer("📸 Analyzing...")
    
    # Get highest resolution photo
    photo: PhotoSize = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
            await message.bot.download_file(file.file_path, tmp.name)
            caption = message.caption or "What's in this image?"
            analysis = await analyze_photo(tmp.name, caption)
            await message.answer(f"🖼 <b>Analysis:</b>\n{analysis}")
    
    except Exception as e:
        logger.exception("Photo processing failed: {}", e)
        await message.answer("Couldn't analyze the photo. Try again?")
from __future__ import annotations
from typing import Optional, List, Tuple
import json
from pathlib import Path
from loguru import logger
from google import genai
from google.genai.types import FunctionDeclaration, Tool, GenerateContentConfig, Content, Part
from ..services.profile_completeness_service import ProfileCompletenessService
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..services.memory_orchestrator import MemoryPack
from .tool_schemas import ALL_TOOLS
from ..services.tool_executor import ToolExecutor

PERSONA_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "moti_system.txt"

class ConversationService:
    """
    Generates Moti's responses using Gemini with full memory context and tool calling.
    """

    def __init__(self):
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        
        function_declarations = [
            FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=t["parameters"]
            )
            for t in ALL_TOOLS
        ]
        self.tools = [Tool(function_declarations=function_declarations)]

        self.persona_prompt = self._load_persona()

    def _load_persona(self) -> str:
        if PERSONA_PROMPT_PATH.exists():
            return PERSONA_PROMPT_PATH.read_text(encoding="utf-8")
        logger.warning("Persona prompt not found; using default")
        return (
            "You are Moti, a proactive, caring planning assistant. "
            "You help users organize their day, track habits, and stay motivated. "
            "Be warm, concise, and action-oriented."
        )

    async def respond_with_tools(
        self,
        user_message: str,
        memory_pack: MemoryPack,
        chat_id: int,
        tool_executor: ToolExecutor,
        session: AsyncSession,
        conversation_history: Optional[List[Content]] = None,
        user_time: str = "00:00",
    ) -> Tuple[str, List[Content]]:
        """
        Generate a response with potential tool calls.
        Returns the final text response and the full conversation history.
        """
        context_dict = memory_pack.to_context_dict()
        context_block = f"<UserContext>\n{json.dumps(context_dict, indent=2, ensure_ascii=False)}\n</UserContext>"
        time_block = f"<KnowledgeBase>Current time: {user_time}</KnowledgeBase>"
        system_instruction = f"{self.persona_prompt}\n\n{context_block}\n\n{time_block}"
        
        messages = conversation_history or []

        gemini_config = GenerateContentConfig(
                system_instruction=system_instruction,
                tools=self.tools,
                max_output_tokens=4084,
                temperature=0.7,
                top_p=0.95,
                top_k=40,
            )
        
        try:
            chat = self.client.aio.chats.create(model=settings.GEMINI_MODEL_ID, config=gemini_config, history=messages)

            response = await chat.send_message(user_message)

            # Check for function calls
            if response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'function_call') and part.function_call:
                        func_call = part.function_call
                        logger.info("Tool call requested: {}", func_call.name)
                        
                        # Execute tool
                        result = await tool_executor.execute(
                            func_call.name,
                            dict(func_call.args),
                            chat_id=chat_id,
                            user_id=memory_pack.user.id,
                        )
                        
                        # Send function response back to model as a Part
                        func_part = Part.from_function_response(
                            name=func_call.name,
                            response={"result": result}
                        )

                        # chat.send_message expects plain parts (str, File, Part, etc.)
                        response = await chat.send_message(func_part)

            # Extract final text
            final_text = response.text.strip() if response.text else "Done! ✅"
            logger.info("Moti responded: {}", final_text[:100])
            
            if "?" in final_text:
                await ProfileCompletenessService.increment_question_count(session, memory_pack.user.id)
    
            # Track interaction
            await ProfileCompletenessService.increment_interaction_count(session, memory_pack.user.id)
    
            # Decay question frequency periodically
            pc = await ProfileCompletenessService.get_or_create(session, memory_pack.user.id)
            if pc.total_interactions % 10 == 0:  # Every 10 interactions
                await ProfileCompletenessService.decay_question_frequency(session, memory_pack.user.id)
            
            return final_text, chat.get_history()

        except Exception as e:
            logger.exception("Gemini conversation with tools failed: {}", e)
            return "Oops, I had a moment there. Can you try again?", conversation_history or []
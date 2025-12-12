from __future__ import annotations
from typing import Optional, List, Tuple, Any
import json
from pathlib import Path
from loguru import logger

from sqlalchemy.ext.asyncio import AsyncSession
from ..config import settings
from ..services.memory_orchestrator import MemoryPack
from .tool_schemas import ALL_TOOLS
from ..services.tool_executor import ToolExecutor
from ..services.profile_completeness_service import ProfileCompletenessService
from .client import async_client

PERSONA_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "moti_system.txt"

class ConversationService:
    """
    Generates Motivi's responses using OpenRouter/OpenAI API with full memory context and tool calling.
    """

    def __init__(self):
        self.client = async_client
        self.persona_prompt = self._load_persona()

    def _load_persona(self) -> str:
        if PERSONA_PROMPT_PATH.exists():
            return PERSONA_PROMPT_PATH.read_text(encoding="utf-8")
        return "You are Motivi, a proactive planning assistant."

    async def respond_with_tools(
        self,
        user_message: str,
        memory_pack: MemoryPack,
        chat_id: int,
        tool_executor: ToolExecutor,
        session: AsyncSession,
        conversation_history: Optional[List[dict]] = None,
    ) -> Tuple[str, List[dict]]:
        """
        Generate a response with potential tool calls using the OpenAI compatible API.
        Returns final text and updated history (as list of dicts).
        """
        context_dict = memory_pack.to_context_dict()
        context_block = f"<UserContext>\n{json.dumps(context_dict, indent=2, ensure_ascii=False)}\n</UserContext>"
        system_instruction = f"{self.persona_prompt}\n\n{context_block}"
        
        # 1. Prepare Messages
        messages = [{"role": "system", "content": system_instruction}]
        
        # Add history (ensure format is correct)
        if conversation_history:
            messages.extend(conversation_history)
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})

        try:
            # 2. First Call to LLM
            response = await self.client.chat.completions.create(
                model=settings.LLM_MODEL_ID,
                messages=messages,
                tools=ALL_TOOLS,
                tool_choice="auto", 
                temperature=0.7,
                max_tokens=4000
            )

            response_msg = response.choices[0].message
            tool_calls = response_msg.tool_calls

            # 3. Handle Tool Calls
            if tool_calls:
                # Add the assistant's message with tool_calls to history
                messages.append(response_msg)
                
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    
                    logger.info(f"Tool call requested: {function_name}")

                    # Execute tool
                    tool_result = await tool_executor.execute(
                        function_name,
                        function_args,
                        chat_id=chat_id,
                        user_id=memory_pack.user.id,
                    )

                    # Append result to messages
                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": json.dumps({"result": tool_result}, ensure_ascii=False)
                    })

                # 4. Second Call to LLM (with tool results)
                second_response = await self.client.chat.completions.create(
                    model=settings.LLM_MODEL_ID,
                    messages=messages,
                    # We usually don't need tools in the follow-up, but keeping them allows multi-step
                    tools=ALL_TOOLS, 
                    temperature=0.7
                )
                final_text = second_response.choices[0].message.content
                
                # Update history with the final assistant response
                messages.append({"role": "assistant", "content": final_text})

            else:
                # No tools called
                final_text = response_msg.content
                messages.append({"role": "assistant", "content": final_text})

            final_text = final_text.strip() if final_text else "Done! ✅"
            logger.info(f"Motivi responded: {final_text[:100]}")

            # 5. Side Effects (Profile scoring)
            if "?" in final_text:
                await ProfileCompletenessService.increment_question_count(session, memory_pack.user.id)
            await ProfileCompletenessService.increment_interaction_count(session, memory_pack.user.id)
            
            pc = await ProfileCompletenessService.get_or_create(session, memory_pack.user.id)
            if pc.total_interactions % 10 == 0:
                await ProfileCompletenessService.decay_question_frequency(session, memory_pack.user.id)

            # Return plain text and the conversation history (excluding system prompt for storage)
            # Filter out the first system message for storage
            history_to_save = [m for m in messages if isinstance(m, dict) and m.get("role") != "system"]
            # Also, if we have tool objects (ChatCompletionMessage), convert to dict
            clean_history = []
            for m in history_to_save:
                if hasattr(m, "model_dump"):
                    clean_history.append(m.model_dump())
                else:
                    clean_history.append(m)

            return final_text, clean_history

        except Exception as e:
            logger.exception(f"Conversation error: {e}")
            return "Oops, I had a moment there. Can you try again?", conversation_history or []
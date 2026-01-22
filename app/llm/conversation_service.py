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
        max_iterations: int = 5,
    ) -> Tuple[str, List[dict]]:
        """
        Generate a response with potential tool calls using the OpenAI compatible API.
        Implements ReAct pattern allowing multiple rounds of tool calling.
        Returns final text and updated history (as list of dicts).
        """
        context_dict = memory_pack.to_context_dict()
        context_block = f"<UserContext>\n{json.dumps(context_dict, indent=2, ensure_ascii=False)}\n</UserContext>"
        system_instruction = f"{self.persona_prompt}\n\n{context_block}"
        
        # 1. Prepare Messages
        # Always start with fresh system message (contains current memory context)
        messages = [{"role": "system", "content": system_instruction}]
        
        # Add conversation history (user/assistant exchanges only, no old system messages)
        if conversation_history:
            for msg in conversation_history:
                # Skip system messages from history since we have a fresh one
                if msg.get("role") != "system":
                    messages.append(msg)
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})

        try:
            # ReAct Loop: Allow multiple rounds of tool calling
            iteration = 0
            final_text = None
            
            while iteration < max_iterations:
                iteration += 1
                logger.debug(f"ReAct iteration {iteration}/{max_iterations}")
                
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

                # If no tool calls, we have the final response
                if not tool_calls:
                    final_text = response_msg.content
                    messages.append({"role": "assistant", "content": final_text})
                    break
                
                # Handle tool calls
                logger.info(f"Processing {len(tool_calls)} tool call(s) in iteration {iteration}")
                
                # Add the assistant's message with tool_calls to history
                # Convert to dict for storage
                assistant_msg_dict = {
                    "role": "assistant",
                    "content": response_msg.content,
                    "tool_calls": []
                }
                
                for tc in tool_calls:
                    assistant_msg_dict["tool_calls"].append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    })
                
                messages.append(assistant_msg_dict)
                
                # Execute all tool calls
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    
                    logger.info(f"Executing tool: {function_name} with args: {function_args}")

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
                
                # Continue loop - LLM will decide if it needs more tools or can respond
            
            # If we exhausted iterations without a final response
            if final_text is None:
                logger.warning(f"Reached max iterations ({max_iterations}) without final response")
                final_text = "Я выполнила все необходимые действия. Чем ещё могу помочь?"
                messages.append({"role": "assistant", "content": final_text})

            final_text = final_text.strip() if final_text else "Готово! Чем ещё могу помочь?"

            # Side Effects (Profile scoring)
            if "?" in final_text:
                await ProfileCompletenessService.increment_question_count(session, memory_pack.user.id)
            await ProfileCompletenessService.increment_interaction_count(session, memory_pack.user.id)
            
            pc = await ProfileCompletenessService.get_or_create(session, memory_pack.user.id)
            if pc.total_interactions % 10 == 0:
                await ProfileCompletenessService.decay_question_frequency(session, memory_pack.user.id)

            # Return plain text and the conversation history (excluding system prompt for storage)
            # The system message is regenerated each turn with fresh context, so don't save it
            # We only save user and assistant text exchanges for context
            history_to_save = []
            for m in messages:
                # Convert ChatCompletionMessage objects to dict if needed
                if hasattr(m, "model_dump"):
                    m = m.model_dump()
                
                # Only save user and assistant messages with text content
                # Skip: system messages (regenerated each turn), tool messages (internal mechanics)
                if isinstance(m, dict):
                    role = m.get("role")
                    content = m.get("content")
                    
                    if role in ["user", "assistant"] and content:
                        history_to_save.append({"role": role, "content": content})

            return final_text, history_to_save

        except Exception as e:
            logger.exception(f"Conversation error: {e}")
            return "Oops, I had a moment there. Can you try again?", conversation_history or []
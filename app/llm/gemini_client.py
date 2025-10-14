from __future__ import annotations
from typing import Any, Dict
from google import genai
from loguru import logger
from ..config import settings
import json

client = genai.Client(api_key=settings.GEMINI_API_KEY)

system_prompt = (
        "You are a structured data extractor. "
        "Extract occupation data as compact JSON with keys: "
        "title (string), employer (string|null), seniority (string|null), "
        "domain (string|null), skills (array of strings), responsibilities (array of strings), "
        "schedule_pattern (string|null). No extra commentary."
    )

async def parse_occupation_to_json(text: str) -> Dict[str, Any]:
    """
    Uses Gemini to parse a free-text occupation description into structured JSON.
    """
    # Prefer JSON response
    try:
        response = await client.aio.models.generate_content(
            model=settings.GEMINI_MODEL_ID,
            contents=genai.types.Content(role='user', parts=[genai.types.Part.from_text(text=text)]),
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
                response_mime_type="application/json"
            )
        )
        if not response or not response.text:
            raise ValueError("Empty response from Gemini")
        response_text = response.candidates[0].content.parts[0].text
        
        return json.loads(response_text)
    
    except Exception as e:
        logger.exception("Gemini parse_occupation_to_json failed: {}", e)
        # Fallback minimal structure
        return {
            "title": None,
            "employer": None,
            "seniority": None,
            "domain": None,
            "skills": [],
            "responsibilities": [],
            "schedule_pattern": None,
        }
from __future__ import annotations
from typing import Any, Dict
from loguru import logger
from ..config import settings
from .client import async_client
import json

system_prompt = (
        "You are a structured data extractor. "
        "Extract occupation data as compact JSON with keys: "
        "title (string), employer (string|null), seniority (string|null), "
        "domain (string|null), skills (array of strings), responsibilities (array of strings), "
        "schedule_pattern (string|null). No extra commentary."
    )

async def parse_occupation_to_json(text: str) -> Dict[str, Any]:
    """
    Uses OpenRouter/OpenAI to parse a free-text occupation description into structured JSON.
    """
    try:
        response = await async_client.chat.completions.create(
            model=settings.LLM_MODEL_ID,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.2,
            extra_body={
                "response_format": {"type": "json_object"}
            }
        )
        if not response or not response.choices:
            raise ValueError("Empty response from API")
        response_text = response.choices[0].message.content
        
        return json.loads(response_text)
    
    except Exception as e:
        logger.exception(f"parse_occupation_to_json failed: {e}")
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
from __future__ import annotations
import base64
from loguru import logger
from ..config import settings
from ..llm.client import async_client

async def analyze_photo(image_path: str, prompt: str = "Describe this image.") -> str:
    """
    Analyze image using OpenAI compatible API (Vision).
    """
    try:
        # Encode image to base64
        with open(image_path, "rb") as img_file:
            base64_image = base64.b64encode(img_file.read()).decode('utf-8')

        response = await async_client.chat.completions.create(
            model=settings.LLM_MODEL_ID, # Ensure the model ID supports vision (e.g. gemini-flash)
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=300
        )
        
        result = response.choices[0].message.content.strip()
        logger.info(f"Image analysis: {result[:100]}")
        return result
    
    except Exception as e:
        logger.exception(f"Vision analysis failed: {e}")
        return "I couldn't analyze this image."
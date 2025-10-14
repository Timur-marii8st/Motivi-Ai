from __future__ import annotations
from google import genai
from loguru import logger
from ..config import settings

client = genai.Client(api_key=settings.GEMINI_API_KEY)

async def analyze_photo(image_path: str, prompt: str = "Describe this image.") -> str:
    """
    Analyze image using Gemini Vision.
    """
    try:
        with open(image_path, "rb") as img_file:
            image_bytes = img_file.read()
        
        response = await client.aio.models.generate_content(
            model=settings.GEMINI_MODEL_ID, contents=[
                genai.types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                genai.types.Part.from_text(text=prompt)   # Maybe need to be in 'user' role, and without "from_text", only prompt
            ]
        )
        
        result = response.text.strip()
        logger.info("Image analysis: {}", result[:100])
        return result
    
    except Exception as e:
        logger.exception("Vision analysis failed: {}", e)
        return "I couldn't analyze this image."
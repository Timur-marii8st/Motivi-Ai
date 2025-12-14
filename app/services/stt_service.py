from __future__ import annotations
import base64
from loguru import logger
from ..config import settings
from ..llm.client import async_client


async def transcribe_voice(audio_path: str) -> str:
    """
    Transcribe audio file using OpenAI compatible API with AUDIO_IMAGE_MODEL_ID.
    Sends audio as base64 encoded data similar to vision service.
    """
    try:
        # Read and encode audio to base64
        with open(audio_path, "rb") as audio_file:
            base64_audio = base64.b64encode(audio_file.read()).decode('utf-8')

        response = await async_client.chat.completions.create(
            model=settings.AUDIO_IMAGE_MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Transcribe the audio"
                        },
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64_audio,
                                "format": "wav"
                            }
                        }
                    ]
                }
            ]
        )
        
        transcript = response.choices[0].message.content.strip()
        logger.info("Transcribed audio: {}", transcript[:100])
        return transcript
    
    except Exception as e:
        logger.exception("Transcription failed: {}", e)
        return ""
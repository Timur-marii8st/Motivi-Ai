from __future__ import annotations
from faster_whisper import WhisperModel
from loguru import logger
import asyncio
import functools

# Load model once (use base or small for speed/accuracy balance)
# For production, cache this or use GPU
_model = None

def get_whisper_model():
    global _model
    if _model is None:
        _model = WhisperModel("base", device="cpu", compute_type="int8")
        logger.info("Whisper model loaded")
    return _model

# Define the blocking operation
def _run_transcribe(model, audio_path):
    segments, info = model.transcribe(audio_path, beam_size=5)
    return " ".join([seg.text for seg in segments])

async def transcribe_voice(audio_path: str) -> str:
    """
    Transcribe audio file using faster-whisper.
    """
    try:
        model = get_whisper_model()
        loop = asyncio.get_running_loop()
        
        # Run blocking call in executor
        transcript = await loop.run_in_executor(
            None, # uses default executor
            functools.partial(_run_transcribe, model, audio_path)
        )
        logger.info("Transcribed audio: {}", transcript[:100])
        return transcript.strip()
    
    except Exception as e:
        logger.exception("Transcription failed: {}", e)
        return ""
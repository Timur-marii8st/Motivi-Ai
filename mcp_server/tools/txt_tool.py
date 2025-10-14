from __future__ import annotations
from pathlib import Path
import aiofiles
from loguru import logger
import os

from ..config import mcp_settings

async def create_txt(filename: str, text: str) -> Path:
    """
    Create a plain text file.
    """
    safe_filename = os.path.basename(filename)
    if not safe_filename.endswith(".txt"):
        safe_filename += ".txt"
    
    file_path = Path(mcp_settings.TEMP_FILES_DIR) / safe_filename
    
    async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
        await f.write(text)
    
    logger.info("Created txt: {}", file_path)
    return file_path
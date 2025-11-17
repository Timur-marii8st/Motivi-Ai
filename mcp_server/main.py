from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI, HTTPException, Depends, Header
from loguru import logger
from contextlib import asynccontextmanager

from .config import mcp_settings
from .tools import telegram_tool

# Ensure temp dir exists
Path(mcp_settings.TEMP_FILES_DIR).mkdir(parents=True, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), level=mcp_settings.LOG_LEVEL)
    logger.info("MCP Tool Server started")
    yield
    logger.info("MCP Tool Server shutdown")

app = FastAPI(title="Motivi MCP Server", lifespan=lifespan)

# Security dependency
async def verify_token(authorization: str = Header(...)):
    expected = f"Bearer {mcp_settings.MCP_SECRET_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=403, detail="Invalid token")

@app.get("/health")
async def health():
    return {"status": "ok"}

# Tool endpoints
from .schemas import (
    SendFileRequest,
    SendPinMessageRequest
)

@app.post("/tools/send_file", dependencies=[Depends(verify_token)])
async def send_file_endpoint(req: SendFileRequest):
    try:
        message_id = await telegram_tool.send_file(
            chat_id=req.chat_id,
            file_path=req.file_path,
            caption=req.caption,
        )
        return {"success": True, "message_id": message_id}
    except Exception as e:
        logger.exception("send_file failed")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tools/send_telegram_message_and_pin", dependencies=[Depends(verify_token)])
async def send_telegram_message_and_pin_endpoint(req: SendPinMessageRequest):
    try:
        await telegram_tool.send_telegram_message_and_pin(
            chat_id=req.chat_id,
            message_text=req.message_text,
            disable_notification=req.disable_notification,
        )
        return {"success": True}
    except Exception as e:
        logger.exception("send_telegram_message_and_pin failed")
        raise HTTPException(status_code=500, detail=str(e))
from pydantic import BaseModel
from typing import Optional, List

class Section(BaseModel):
    heading: str
    content: str

class CreateDocxRequest(BaseModel):
    chat_id: int
    title: str
    sections: List[Section]
    footer: Optional[str] = None

class CreateTxtRequest(BaseModel):
    chat_id: int
    filename: str
    text: str

class SendFileRequest(BaseModel):
    chat_id: int
    file_path: str
    caption: Optional[str] = None

class SendPinMessageRequest(BaseModel):
    chat_id: int
    message_text: str
    disable_notification: bool = True
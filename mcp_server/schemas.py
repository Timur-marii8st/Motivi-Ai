from pydantic import BaseModel
from typing import Optional, List

class Section(BaseModel):
    heading: str
    content: str

class SendFileRequest(BaseModel):
    chat_id: int
    file_path: str
    caption: Optional[str] = None
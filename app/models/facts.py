from pydantic import BaseModel, field_validator
from typing import List, Literal

class Fact(BaseModel):
    fact: str
    importance: Literal["Core", "Episode", "Working"]

    # Validation to ensure no empty strings
    @field_validator('fact')
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Field cannot be empty')
        return v.strip()
    
    # Normalize importance to have consistent casing
    @field_validator('importance')
    @classmethod
    def normalize_importance(cls, v: str) -> str:
        return v.capitalize()

class FactExtraction(BaseModel):
    personal_information: List[Fact]
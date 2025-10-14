from __future__ import annotations
from typing import Optional
from zoneinfo import available_timezones

def is_valid_timezone(tz: str) -> bool:
    return tz in available_timezones()

def clamp_age(age_str: str) -> Optional[int]:
    try:
        age = int(age_str)
        if 5 <= age <= 120:
            return age
        return None
    except Exception:
        return None
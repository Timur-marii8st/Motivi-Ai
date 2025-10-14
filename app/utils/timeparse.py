from __future__ import annotations
from datetime import time
from typing import Optional

def parse_hhmm(s: str) -> Optional[time]:
    try:
        parts = s.strip().split(":")
        if len(parts) != 2:
            return None
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return time(hour=h, minute=m)
    except Exception:
        return None
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

def get_time_in_zone(tz_name: Optional[str]) -> str:
    """
    Получает текущее время в указанной временной зоне в формате ISO.
    Если tz_name равен None, возвращает время в UTC.
    """
    now_utc = datetime.now(timezone.utc)
    
    if not tz_name:
        return now_utc.isoformat()
    
    try:
        zone = ZoneInfo(tz_name)
    except Exception as e:
        # Если timezone невалидный, возвращаем UTC время
        return now_utc.isoformat()
    
    now_in_zone = now_utc.astimezone(zone).isoformat()
    return now_in_zone
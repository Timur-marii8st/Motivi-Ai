from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo
from loguru import logger

def get_time_in_zone(tz_name: Optional[str]) -> str:
    now_utc = datetime.now(timezone.utc)
    
    # Определяем целевую таймзону
    target_zone = timezone.utc  # По умолчанию UTC
    if tz_name:
        try:
            target_zone = ZoneInfo(tz_name)
        except Exception as e:
            logger.warning(f"Invalid timezone '{tz_name}', falling back to UTC: {e}")
            # Если ошибка, остаемся в UTC

    # Переводим время в нужную зону
    now_in_zone = now_utc.astimezone(target_zone)
    
    # Форматируем строку: Год-Месяц-День T Часы:Минуты
    return now_in_zone.strftime('%Y-%m-%dT%H:%M')
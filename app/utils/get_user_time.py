from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def get_time_in_zone(tz_name: str) -> datetime:
    now_utc = datetime.now(timezone.utc)
    try:
        zone = ZoneInfo(tz_name)
    except Exception as e:
        raise ValueError(f"Unknown timezone {tz_name!r}") from e
    now_in_zone = now_utc.astimezone(zone).isoformat()
    return now_in_zone
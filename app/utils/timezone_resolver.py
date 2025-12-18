from __future__ import annotations
from zoneinfo import available_timezones
from typing import Optional, Union, List

# A small mapping for common city names -> IANA timezones
_COMMON_CITY_TO_TZ = {
    # --- Russia & CIS (Россия и СНГ) ---
    "moscow": "Europe/Moscow",
    "moskva": "Europe/Moscow",
    "saint_petersburg": "Europe/Moscow",
    "st_petersburg": "Europe/Moscow",
    "spb": "Europe/Moscow",
    "kazan": "Europe/Moscow",
    "novosibirsk": "Asia/Novosibirsk",
    "yekaterinburg": "Asia/Yekaterinburg",
    "ekaterinburg": "Asia/Yekaterinburg",
    "kaliningrad": "Europe/Kaliningrad",
    "samara": "Europe/Samara",
    "omsk": "Asia/Omsk",
    "krasnoyarsk": "Asia/Krasnoyarsk",
    "irkutsk": "Asia/Irkutsk",
    "yakutsk": "Asia/Yakutsk",
    "vladivostok": "Asia/Vladivostok",
    "magadan": "Asia/Magadan",
    "kamchatka": "Asia/Kamchatka",
    "minsk": "Europe/Minsk",
    "kiev": "Europe/Kyiv",
    "kyiv": "Europe/Kyiv",
    "almaty": "Asia/Almaty",
    "astana": "Asia/Almaty",  # Или Asia/Qyzylorda в зависимости от региона, но чаще Almaty как база
    "tashkent": "Asia/Tashkent",
    "tbilisi": "Asia/Tbilisi",
    "yerevan": "Asia/Yerevan",
    "baku": "Asia/Baku",

    # --- Europe (Европа) ---
    "london": "Europe/London",
    "dublin": "Europe/Dublin",
    "paris": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "madrid": "Europe/Madrid",
    "rome": "Europe/Rome",
    "amsterdam": "Europe/Amsterdam",
    "brussels": "Europe/Brussels",
    "vienna": "Europe/Vienna",
    "warsaw": "Europe/Warsaw",
    "prague": "Europe/Prague",
    "budapest": "Europe/Budapest",
    "stockholm": "Europe/Stockholm",
    "copenhagen": "Europe/Copenhagen",
    "oslo": "Europe/Oslo",
    "helsinki": "Europe/Helsinki",
    "athens": "Europe/Athens",
    "istanbul": "Europe/Istanbul",
    "lisbon": "Europe/Lisbon",
    "zurich": "Europe/Zurich",
    "geneva": "Europe/Zurich",
    "belgrade": "Europe/Belgrade",

    # --- North America (Северная Америка) ---
    "new_york": "America/New_York",
    "newyork": "America/New_York",
    "nyc": "America/New_York",
    "washington": "America/New_York",
    "boston": "America/New_York",
    "miami": "America/New_York",
    "atlanta": "America/New_York",
    "toronto": "America/Toronto",
    "montreal": "America/Toronto",
    "chicago": "America/Chicago",
    "houston": "America/Chicago",
    "dallas": "America/Chicago",
    "mexico_city": "America/Mexico_City",
    "denver": "America/Denver",
    "phoenix": "America/Phoenix",  # Нет перехода на летнее время
    "los_angeles": "America/Los_Angeles",
    "la": "America/Los_Angeles",
    "san_francisco": "America/Los_Angeles",
    "sf": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "las_vegas": "America/Los_Angeles",
    "vancouver": "America/Vancouver",
    "anchorage": "America/Anchorage",
    "honolulu": "Pacific/Honolulu",
    "hawaii": "Pacific/Honolulu",

    # --- South America (Южная Америка) ---
    "sao_paulo": "America/Sao_Paulo",
    "rio_de_janeiro": "America/Sao_Paulo",
    "brasilia": "America/Sao_Paulo",
    "buenos_aires": "America/Argentina/Buenos_Aires",
    "santiago": "America/Santiago",
    "bogota": "America/Bogota",
    "lima": "America/Lima",
    "caracas": "America/Caracas",

    # --- Asia & Middle East (Азия и Ближний Восток) ---
    "tokyo": "Asia/Tokyo",
    "osaka": "Asia/Tokyo",
    "seoul": "Asia/Seoul",
    "shanghai": "Asia/Shanghai",
    "beijing": "Asia/Shanghai",
    "peking": "Asia/Shanghai",
    "hong_kong": "Asia/Hong_Kong",
    "hk": "Asia/Hong_Kong",
    "taipei": "Asia/Taipei",
    "singapore": "Asia/Singapore",
    "bangkok": "Asia/Bangkok",
    "hanoi": "Asia/Bangkok",
    "jakarta": "Asia/Jakarta",
    "kuala_lumpur": "Asia/Kuala_Lumpur",
    "manila": "Asia/Manila",
    "mumbai": "Asia/Kolkata",
    "kolkata": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "new_delhi": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata",
    "karachi": "Asia/Karachi",
    "dubai": "Asia/Dubai",
    "abu_dhabi": "Asia/Dubai",
    "riyadh": "Asia/Riyadh",
    "tehran": "Asia/Tehran",
    "tel_aviv": "Asia/Tel_Aviv",
    "jerusalem": "Asia/Jerusalem",

    # --- Australia & Oceania (Австралия и Океания) ---
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "brisbane": "Australia/Brisbane",
    "perth": "Australia/Perth",
    "adelaide": "Australia/Adelaide",
    "auckland": "Pacific/Auckland",
    "wellington": "Pacific/Auckland",

    # --- Africa (Африка) ---
    "cairo": "Africa/Cairo",
    "johannesburg": "Africa/Johannesburg",
    "capetown": "Africa/Johannesburg",
    "lagos": "Africa/Lagos",
    "nairobi": "Africa/Nairobi",
    "casablanca": "Africa/Casablanca",
}


def _normalize_city(city: str) -> str:
    return city.strip().lower().replace(" ", "_")


def resolve_timezone_from_city(city: str) -> Optional[Union[str, List[str]]]:
    """Try to resolve an IANA timezone from a city name.

    Returns:
        - str timezone when a clear mapping or single match is found
        - list of str candidates when ambiguous
        - None when no candidate found
    """
    if not city:
        return None

    nc = _normalize_city(city)
    if nc in _COMMON_CITY_TO_TZ:
        return _COMMON_CITY_TO_TZ[nc]

    # try to find zones that contain the city substring
    candidates = [tz for tz in available_timezones() if nc in tz.lower()]

    if not candidates:
        # try matching the last part of zone
        candidates = [tz for tz in available_timezones() if tz.split("/")[-1].lower() == nc]

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    # ambiguous
    return candidates

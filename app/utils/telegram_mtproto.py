from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


_PHONE_CLEAN_RE = re.compile(r"[\s\-\(\)\u00A0\u200B\u200E\u200F]+")


def normalize_phone_number(raw: str) -> str:
    """
    Normalize a phone number typed by the user into a Telethon-friendly format.

    Keeps a leading "+" when present and removes common separators/invisible
    whitespace that users often paste from mobile keyboards.
    """
    phone = _PHONE_CLEAN_RE.sub("", (raw or "").strip())
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    return phone


def is_valid_international_phone(phone: str) -> bool:
    """Basic E.164-like validation used before calling Telethon."""
    return bool(re.fullmatch(r"\+[1-9]\d{7,14}", phone or ""))


def build_telethon_proxy(proxy_url: str) -> tuple[Any, ...] | None:
    """
    Convert a proxy URL from settings into the tuple format accepted by Telethon.

    Supported schemes:
    - socks5 / socks5h
    - socks4 / socks4a
    - http / https
    """
    if not proxy_url:
        return None

    parsed = urlparse(proxy_url.strip())
    if not parsed.scheme or not parsed.hostname or not parsed.port:
        return None

    scheme = parsed.scheme.lower()
    proxy_type_map = {
        "socks5": "socks5",
        "socks5h": "socks5",
        "socks4": "socks4",
        "socks4a": "socks4",
        "http": "http",
        "https": "http",
    }
    proxy_type = proxy_type_map.get(scheme)
    if not proxy_type:
        return None

    username = parsed.username
    password = parsed.password
    rdns = scheme.endswith("h") or scheme.endswith("a")

    if username or password:
        return (
            proxy_type,
            parsed.hostname,
            parsed.port,
            rdns,
            username,
            password,
        )

    if rdns:
        return (proxy_type, parsed.hostname, parsed.port, rdns)

    return (proxy_type, parsed.hostname, parsed.port)

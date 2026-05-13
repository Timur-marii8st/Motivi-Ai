from app.utils.telegram_mtproto import (
    build_telethon_proxy,
    is_valid_international_phone,
    normalize_phone_number,
)


def test_normalize_phone_number_removes_separators_and_zero_width_spaces():
    raw = "\u200e+7 (996) 952-70-40\u200f"
    assert normalize_phone_number(raw) == "+79969527040"
    assert is_valid_international_phone(normalize_phone_number(raw)) is True


def test_normalize_phone_number_converts_00_prefix():
    phone = normalize_phone_number("0079969527040")
    assert phone == "+79969527040"
    assert is_valid_international_phone(phone) is True


def test_build_telethon_proxy_for_socks5():
    assert build_telethon_proxy("socks5://singbox:1080") == ("socks5", "singbox", 1080)


def test_build_telethon_proxy_for_authenticated_socks5h():
    assert build_telethon_proxy("socks5h://user:pass@host.example:9999") == (
        "socks5",
        "host.example",
        9999,
        True,
        "user",
        "pass",
    )

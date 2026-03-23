---
name: Telegram VPN proxy setup
description: How to bypass Telegram API blocks on Russian servers using sing-box VLESS proxy in Docker
type: reference
---

## Проблема

Telegram API (`api.telegram.org`) блокируется/замедляется РКН на российских серверах.
Бот не может подключиться: `TelegramNetworkError: Cannot connect to host api.telegram.org:443`.

## Решение

sing-box контейнер в docker-compose как SOCKS5 прокси через VLESS+Reality туннель.

### Архитектура

```
Bot container → socks5://singbox:1080 → sing-box (VLESS+Reality) → api.telegram.org ✅
```

### Ключевые файлы

- `infra/docker-compose.yml` — сервис `singbox` + переменная `TELEGRAM_API_PROXY` в боте
- `infra/singbox/config.json` — конфиг sing-box (в .gitignore, содержит VPN-креденшалы)
- `bot/app/config.py` — настройка `telegram_api_proxy`
- `bot/app/main.py` — создание `AiohttpSession(proxy=...)` для aiogram

### Грабли при настройке

1. **sing-box без команды `run`** — по умолчанию просто печатает help. Нужно: `command: run -c /etc/sing-box/config.json`
2. **aiogram требует `aiohttp-socks`** для любого прокси (даже HTTP). Без него: `ModuleNotFoundError: No module named 'aiohttp_socks'`
3. **sing-box latest (1.13+) удалил `dns` outbound** — `FATAL: dns outbound is deprecated`. Решение: убрать `"type": "dns"` из outbounds и DNS route rules из конфига. Для простого прокси DNS-роутинг не нужен.
4. **sing-box latest (1.12+) deprecated legacy DNS format** — можно обойти переменной `ENABLE_DEPRECATED_LEGACY_DNS_SERVERS=true`, но проще вообще убрать секцию `dns` из конфига.
5. **Docker DNS** — добавить `dns: 8.8.8.8, 1.1.1.1` в бот-сервис для резолва через Google DNS.
6. **Конфиг в .gitignore** — `infra/singbox/config.json` содержит UUID/ключи VPN-подписки, не коммитить. Копировать на сервер через `scp`.

### VPN-провайдер

Пользователь использует **your.vpn** через клиент **Hiddify** (протокол VLESS+Reality).
Конфиг — формат sing-box. Серверы: Netherlands, Germany и др.

### Минимальный рабочий config.json

```json
{
  "log": {"level": "info", "timestamp": true},
  "inbounds": [
    {"type": "mixed", "tag": "mixed-in", "listen": "0.0.0.0", "listen_port": 1080, "sniff": true, "sniff_override_destination": true}
  ],
  "outbounds": [
    {"type": "urltest", "tag": "auto", "outbounds": ["server1", "server2"], "url": "http://cp.cloudflare.com/", "interval": "5m0s"},
    {"type": "vless", "tag": "server1", "server": "...", "server_port": 443, "uuid": "...", "flow": "xtls-rprx-vision", "tls": {"enabled": true, "server_name": "...", "utls": {"enabled": true, "fingerprint": "firefox"}, "reality": {"enabled": true, "public_key": "..."}}, "packet_encoding": "xudp"},
    {"type": "direct", "tag": "direct"}
  ],
  "route": {"final": "auto", "auto_detect_interface": true}
}
```

### Деплой на сервер

```bash
# Копировать конфиг
scp -i id_rsa "infra/singbox/config.json" user@server:~/Cursachizi/infra/singbox/

# Пересобрать
docker compose -f infra/docker-compose.yml up -d --build
```

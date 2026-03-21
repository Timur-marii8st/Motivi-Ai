# Security Audit Report -- Motivi-Ai

**Audit date:** 2026-03-21
**Scope:** Full Python codebase, Docker configuration, infrastructure
**Auditor:** Automated security review (Opus 4.6)

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 2     |
| HIGH     | 5     |
| MEDIUM   | 6     |
| LOW      | 4     |

---

## CRITICAL Vulnerabilities

### C-1. HTML Injection in Admin Broadcast

**File:** `app/bot/routers/admin.py`, line 75
**Vulnerability class:** A03:2021 -- Injection (Stored XSS / HTML Injection)
**Severity:** CRITICAL

**Description:** The admin broadcast command injects user-supplied text directly into an HTML-formatted Telegram message without escaping:

```python
await bot.send_message(user.tg_chat_id, f"<b>Объявление:</b>\n\n{broadcast_msg}")
```

**Exploit scenario:** An admin (or an attacker who compromises an admin account) sends `/admin_broadcast <script>...</script>` or more realistically, crafted HTML that could include malicious links disguised as UI elements (e.g., `<a href="https://phishing.site">Click here to verify your account</a>`). Since `parse_mode="HTML"` is the default bot setting, all users receive the rendered HTML. This can be used for phishing attacks against the entire user base.

**Remediation:**
```python
import html
broadcast_msg = html.escape(parts[1])
await bot.send_message(user.tg_chat_id, f"<b>Объявление:</b>\n\n{broadcast_msg}")
```

---

### C-2. Database and Redis Exposed to Host Network Without Authentication

**File:** `docker-compose.yml`, lines 33 and 45
**Vulnerability class:** A01:2021 -- Broken Access Control
**Severity:** CRITICAL

**Description:** Both PostgreSQL and Redis bind to all host interfaces (`0.0.0.0`) via `ports` directives:

```yaml
db:
  ports:
    - "5432:5432"    # PostgreSQL exposed to the internet

redis:
  ports:
    - "6379:6379"    # Redis exposed to the internet (no password)
```

Redis has no authentication configured at all. PostgreSQL credentials come from `.env` but the port is publicly accessible, making it vulnerable to brute-force attacks.

**Exploit scenario:** An attacker scans the public IP, finds open port 6379 (Redis), and gains full access to: FSM state, conversation history, rate limit counters, OAuth state tokens, pending userbot replies, and subscription status cache. They can bypass rate limits, steal OAuth state tokens to hijack Google Calendar connections, or poison cached data. On PostgreSQL, brute-forcing the password (which defaults to `postgres:postgres` in `.env.example`) yields full database access.

**Remediation:**
- Remove the `ports` directives for both `db` and `redis`. They are already on the `motivi-network` bridge and accessible to the `app` container via service names.
- If external access is needed for debugging, bind to `127.0.0.1:5432:5432` instead.
- Add `requirepass` to Redis configuration.
```yaml
db:
  # Remove ports entirely, or:
  ports:
    - "127.0.0.1:5432:5432"

redis:
  command: redis-server --requirepass ${REDIS_PASSWORD}
  ports:
    - "127.0.0.1:6379:6379"
```

---

## HIGH Vulnerabilities

### H-1. Metrics Endpoint Exposes User Counts Without Authentication

**File:** `app/main.py`, lines 140-155
**Vulnerability class:** A01:2021 -- Broken Access Control
**Severity:** HIGH

**Description:** The `/metrics` endpoint returns user and episode counts to any unauthenticated HTTP request. It is gated only by the `ENABLE_METRICS` config flag but has no authentication:

```python
@app.get("/metrics")
async def metrics(session: AsyncSession = Depends(get_session)):
    if not settings.ENABLE_METRICS:
        raise HTTPException(status_code=404)
    # Returns total_users and total_episodes to anyone
```

**Exploit scenario:** If metrics are enabled, any internet user can query `https://domain.com/metrics` to learn the user count and episode count, leaking business intelligence. This is a reconnaissance vector.

**Remediation:** Add bearer token or IP whitelist authentication:
```python
@app.get("/metrics")
async def metrics(
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
):
    if not settings.ENABLE_METRICS:
        raise HTTPException(status_code=404)
    if authorization != f"Bearer {settings.METRICS_SECRET}":
        raise HTTPException(status_code=403)
```

---

### H-2. Nginx Proxy Manager Admin Panel Exposed on Port 81

**File:** `docker-compose.yml`, lines 54-55
**Vulnerability class:** A01:2021 -- Broken Access Control
**Severity:** HIGH

**Description:** The Nginx Proxy Manager service exposes its admin dashboard on port 81:

```yaml
nginx-proxy:
  ports:
    - '80:80'
    - '443:443'
    - '81:81'    # Admin panel accessible from the internet
```

The default credentials for Nginx Proxy Manager are `admin@example.com` / `changeme`.

**Exploit scenario:** An attacker accesses `http://public-ip:81`, logs in with default credentials (or brute-forces them), and gains full control over the reverse proxy. They can redirect traffic, intercept HTTPS, add proxy hosts to internal services, or capture webhook payloads containing Telegram update data.

**Remediation:** Bind port 81 to localhost only:
```yaml
ports:
  - '80:80'
  - '443:443'
  - '127.0.0.1:81:81'
```

---

### H-3. Source Code Mounted Read-Write in Production Container

**File:** `docker-compose.yml`, line 13
**Vulnerability class:** A05:2021 -- Security Misconfiguration
**Severity:** HIGH

**Description:** The app container mounts the entire project directory read-write:

```yaml
volumes:
  - .:/app
```

This means any code path that writes to the filesystem (e.g., a compromised dependency, an application bug) can modify source code files, configuration, or even the `.env` file containing all secrets.

**Exploit scenario:** If an attacker gains code execution within the app container (e.g., through a dependency vulnerability), they can modify `app/main.py` or any other file to inject a backdoor that persists across container restarts. They can also read `.env` directly from disk to exfiltrate all secrets.

**Remediation:** In production, do not mount source code. The Dockerfile already copies the code at build time:
```yaml
# Production:
volumes:
  - shared_files:/tmp/motivi_files
  - /tmp/motivi_exec:/tmp/motivi_exec
# Remove: - .:/app
```

---

### H-4. Exception Messages Leaked to LLM Context via ToolExecutor

**File:** `app/services/tool_executor.py`, lines 55, 312, 351, 416
**Vulnerability class:** A09:2021 -- Security Logging and Monitoring Failures (Information Exposure)
**Severity:** HIGH

**Description:** The `ToolExecutor.execute()` catch-all and several individual handlers return raw exception text to the LLM:

```python
except Exception as e:
    logger.exception("Tool execution failed: {} - {}", tool_name, e)
    return {"success": False, "error": str(e)}
```

The LLM then includes this error in its response to the user. Exception messages can contain internal paths, database connection strings, SQL errors, or stack trace fragments.

**Exploit scenario:** A user sends a message that triggers a tool call which fails (e.g., a malformed calendar event). The raw exception, potentially containing database schema information or internal service details, is returned by the LLM to the user. This aids reconnaissance for further attacks.

**Remediation:** Return generic error messages to the LLM; log the real exception separately:
```python
except Exception as e:
    logger.exception("Tool execution failed: {} - {}", tool_name, e)
    return {"success": False, "error": "An internal error occurred. Please try again."}
```

---

### H-5. OAuth State Token Lookup via SCAN Enables Timing Side Channel

**File:** `app/services/oauth_state_service.py`, lines 54-56
**Vulnerability class:** A02:2021 -- Cryptographic Failures
**Severity:** HIGH

**Description:** The `verify_and_consume_state` method uses `SCAN` to find an OAuth state token because the user_id is embedded in the key but unknown at verification time:

```python
pattern = f"oauth_state:*:{state_token}"
async for key in redis.scan_iter(match=pattern, count=10):
    keys.append(key)
```

This has two problems:
1. **Timing side channel:** SCAN iteration time depends on the number of keys in Redis, and finding a match vs. not finding one produces different timing. An attacker can use this to determine if valid OAuth flows are in progress.
2. **Pattern injection:** If the `state_token` value is not strictly validated, Redis glob metacharacters (`*`, `?`, `[`) in the token could match unintended keys. While `secrets.token_urlsafe(32)` produces safe tokens normally, this is a defense-in-depth concern.

**Exploit scenario:** An attacker with knowledge of the URL pattern sends crafted state parameters with Redis glob characters to potentially match other users' OAuth state tokens.

**Remediation:** Change the key schema so user_id is not required for lookup. Store with a simple key `oauth_state:{token}` and include `user_id` only in the payload:
```python
@classmethod
async def create_and_store_state(cls, user_id: int, chat_id: int) -> str:
    redis = cls._get_redis_client()
    state_token = secrets.token_urlsafe(32)
    payload = {"user_id": user_id, "chat_id": chat_id}
    await redis.set(f"oauth_state:{state_token}", json.dumps(payload), ex=cls.STATE_EXPIRATION_SECONDS)
    return state_token

@classmethod
async def verify_and_consume_state(cls, state_token: str) -> dict | None:
    redis = cls._get_redis_client()
    key = f"oauth_state:{state_token}"
    payload_str = await redis.getdel(key)
    if not payload_str:
        return None
    return json.loads(payload_str)
```

---

## MEDIUM Vulnerabilities

### M-1. Voice/Photo Transcript Not HTML-Escaped Before Display

**File:** `app/bot/routers/multimodal.py`, lines 80 and 144
**Vulnerability class:** A03:2021 -- Injection (HTML Injection)
**Severity:** MEDIUM

**Description:** Transcription results and photo analysis are embedded in HTML messages without escaping:

```python
await message.answer(f"<i>{transcript}</i>")         # line 80
await message.answer(f"<b>Анализ:</b>\n{analysis}")  # line 144
```

**Exploit scenario:** If the STT engine or vision model returns text containing HTML tags (e.g., from a photo of a webpage containing `<b>` tags, or an adversarial audio), Telegram will render them. This could be used to inject misleading formatting or clickable links.

**Remediation:**
```python
import html
await message.answer(f"<i>{html.escape(transcript)}</i>")
await message.answer(f"<b>Анализ:</b>\n{html.escape(analysis)}")
```

---

### M-2. Cleartext Keyset Handle in Tink Encryption

**File:** `app/security/encryption_manager.py`, line 39
**Vulnerability class:** A02:2021 -- Cryptographic Failures
**Severity:** MEDIUM

**Description:** The Tink AEAD keyset is loaded in cleartext from an environment variable:

```python
handle = cleartext_keyset_handle.read(reader)
```

The code contains a comment acknowledging this: "NOTE: Using cleartext keyset handle. For production consider wrapping the keyset with a KMS master key." However, this means the raw encryption key material is stored as a base64 string in the `.env` file and in the process environment, where it can be read by any process running as the same user or via `/proc/<pid>/environ`.

**Exploit scenario:** An attacker who gains read access to the `.env` file or process environment (e.g., via H-3 or a container escape) obtains the raw keyset and can decrypt all encrypted database columns.

**Remediation:** Wrap the keyset with a KMS master key (AWS KMS, GCP KMS, or HashiCorp Vault). At minimum, ensure the `.env` file has restricted permissions (`chmod 600`) and is not mounted into the container (pass secrets via Docker secrets or environment variables from a secret manager).

---

### M-3. Legacy Plaintext Fallback in Encrypted Column Types

**File:** `app/security/encrypted_types.py`, lines 80-90
**Vulnerability class:** A02:2021 -- Cryptographic Failures
**Severity:** MEDIUM

**Description:** When a database value does not start with the `v1:` version prefix, it is returned as-is (plaintext) with only a warning log:

```python
# Legacy plaintext fallback. Return as-is but log a warning
if not self._legacy_warned:
    logger.warning("Returning legacy plaintext value for encrypted column '%s'...", self._label)
    self._legacy_warned = True
return value
```

This means if an attacker gains direct database write access, they can replace any encrypted column value with plaintext, and the application will happily return it. There is no mechanism to detect or reject this downgrade.

**Exploit scenario:** An attacker with database access (via C-2) replaces an encrypted `session_string` with a plaintext Telethon session string they control. The application reads it without complaint. Combined with the row integrity system, this would be caught -- but only if `INTEGRITY_STRICT_MODE` is enabled and the row already has a signature.

**Remediation:** After running the backfill script, remove the plaintext fallback or make it configurable:
```python
if settings.INTEGRITY_STRICT_MODE:
    logger.error("Unencrypted value found in encrypted column '%s' — rejecting", self._label)
    return None  # or raise
```

---

### M-4. Row Integrity Key Derived from Fernet Encryption Key

**File:** `app/security/row_integrity.py`, lines 27-34
**Vulnerability class:** A02:2021 -- Cryptographic Failures
**Severity:** MEDIUM

**Description:** The row integrity HMAC key is derived from the same `ENCRYPTION_KEY` used for Fernet encryption of OAuth tokens:

```python
def _derive_integrity_key() -> bytes:
    raw_key = (settings.ENCRYPTION_KEY or "").strip().encode("utf-8")
    # ...
    return hashlib.sha256(raw_key + b":row-integrity:v1").digest()
```

While the SHA-256 derivation with a domain separator is acceptable, having a single key compromise expose both token encryption AND row integrity verification violates the principle of key separation.

**Exploit scenario:** If `ENCRYPTION_KEY` is leaked, an attacker can both decrypt OAuth tokens AND forge valid integrity signatures for tampered database rows, defeating the entire integrity system.

**Remediation:** Use a separate environment variable for the row integrity key, or derive from `DATA_ENCRYPTION_KEYSET_B64` instead:
```python
# Add to config.py:
ROW_INTEGRITY_KEY: str = Field(default="", description="Separate key for row integrity HMAC")
```

---

### M-5. Decryption Failure Returns None Instead of Raising

**File:** `app/security/encrypted_types.py`, lines 68-78
**Vulnerability class:** A02:2021 -- Cryptographic Failures
**Severity:** MEDIUM

**Description:** When decryption of an encrypted column fails, the exception is caught, logged, and `None` is returned:

```python
try:
    ciphertext = _decode_ciphertext(value)
    plaintext = encryptor.decrypt(ciphertext, aad=self._aad)
    return self._deserializer(plaintext)
except Exception:
    logger.exception("Failed to decrypt encrypted column '%s'...", self._label)
    return None
```

This silently swallows decryption failures. If an attacker tampers with encrypted data in the database, the application returns `None` instead of raising an error. Downstream code may interpret `None` as "value not set" rather than "tampered data detected."

**Exploit scenario:** An attacker corrupts encrypted user data in the database. The application silently treats the corrupted fields as empty/null rather than detecting the tampering, potentially causing the user's encrypted name or settings to appear blank.

**Remediation:** In strict mode, raise the exception so the row integrity system and application error handling can react:
```python
except Exception:
    logger.exception("Failed to decrypt encrypted column '%s'...", self._label)
    if settings.INTEGRITY_STRICT_MODE:
        raise
    return None
```

---

### M-6. Output Dir Created with Mode 0o777

**File:** `app/services/code_executor_service.py`, line 316
**Vulnerability class:** A05:2021 -- Security Misconfiguration
**Severity:** MEDIUM

**Description:** The per-execution output directory on the host is created with world-writable permissions:

```python
os.makedirs(output_host_dir, mode=0o777, exist_ok=False)
```

While this is necessary for the `nobody` user inside the container to write files, on the host side any process can read/write this directory between creation and cleanup.

**Exploit scenario:** In a multi-tenant or shared-host environment, another process could race to write malicious files into the output directory before the executor collects them, or read sensitive output files before they are cleaned up (TOCTOU race).

**Remediation:** Use `0o700` permissions and ensure the container maps the directory ownership correctly, or use Docker's `--user` flag with a known UID and set the directory to that UID:
```python
os.makedirs(output_host_dir, mode=0o700, exist_ok=False)
# In Docker cmd, use explicit UID: "-u", "65534" (nobody)
```

---

## LOW Vulnerabilities

### L-1. `f-string` Logging with Loguru

**File:** Multiple files (conversation_service.py lines 109, 137, 169, 178, 200, 236)
**Vulnerability class:** Best practice violation
**Severity:** LOW

**Description:** Several files use f-strings in loguru calls instead of positional format:

```python
logger.debug(f"ReAct iteration {iteration}/{max_iterations}")
logger.info(f"Processing {len(tool_calls)} tool call(s) in iteration {iteration}")
```

The CLAUDE.md explicitly states: "Use loguru positional-arg format -- NOT f-strings." F-strings in logging calls evaluate their arguments even when the log level is disabled, wasting CPU. More importantly, if user-controlled data ends up in an f-string log call, it could cause format string issues.

**Remediation:** Use positional format:
```python
logger.debug("ReAct iteration {}/{}", iteration, max_iterations)
```

---

### L-2. Webhook Logging Leaks URL with f-string

**File:** `app/main.py`, line 54
**Vulnerability class:** A09:2021 -- Security Logging and Monitoring Failures
**Severity:** LOW

**Description:** The webhook URL (which contains the public domain) is logged with an f-string:

```python
logger.info(f"Webhook set to {webhook_url}")
```

While the webhook URL itself is not secret, this pattern (f-string logging) violates the project convention and, if applied to sensitive data, could leak secrets to logs.

**Remediation:** Use positional format:
```python
logger.info("Webhook set to {}", webhook_url)
```

---

### L-3. Onboarding Summary Does Not Escape User-Provided Name

**File:** `app/bot/routers/onboarding.py`, line 241
**Vulnerability class:** A03:2021 -- Injection (HTML Injection)
**Severity:** LOW

**Description:** The user's name is embedded in an HTML-formatted message without escaping:

```python
f"- Имя: <b>{data.get('name') or 'Не указано'}</b>\n"
```

**Exploit scenario:** A user enters `<a href="http://evil.com">click me</a>` as their name during onboarding. The HTML is rendered in the summary message sent back to them. Since this is reflected back only to the same user, the impact is self-XSS (low severity).

**Remediation:**
```python
import html
name_display = html.escape(data.get('name') or 'Не указано')
f"- Имя: <b>{name_display}</b>\n"
```

---

### L-4. `_EXEC_BASE_DIR` is a Predictable Path Under `/tmp`

**File:** `app/services/code_executor_service.py`, line 94
**Vulnerability class:** A05:2021 -- Security Misconfiguration
**Severity:** LOW

**Description:** The base directory for code execution output is a fixed, predictable path:

```python
_EXEC_BASE_DIR = "/tmp/motivi_exec"
```

While individual subdirectories use UUID names, the base directory is predictable and could be targeted by other processes on the host.

**Exploit scenario:** On a shared host, another process could pre-create `/tmp/motivi_exec` as a symlink pointing elsewhere, potentially causing the executor to create subdirectories in an attacker-controlled location. However, the `os.makedirs(output_host_dir, mode=0o777, exist_ok=False)` with `exist_ok=False` on the subdirectory provides some protection since it would fail if the path already exists.

**Remediation:** Use `tempfile.mkdtemp()` for the base directory or validate that the base directory is not a symlink before use.

---

## Positive Findings (Noteworthy Security Controls)

The following security controls are well-implemented:

1. **Webhook secret validation** (`app/main.py`, line 163) -- Properly checks `X-Telegram-Bot-Api-Secret-Token` header on every request.

2. **Docker sandbox security** (`app/services/code_executor_service.py`) -- Comprehensive container hardening: `--network=none`, `--read-only`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, `--pids-limit=64`, memory limits, CPU throttling, `nobody` user, and symlink traversal protection in output collection.

3. **OAuth CSRF protection** (`app/services/oauth_state_service.py`) -- Uses `secrets.token_urlsafe(32)` for state tokens, stores in Redis with TTL, and consumes (deletes) on use.

4. **Userbot authorization checks** (`app/bot/routers/userbot.py`) -- All callback handlers verify `pending["user_id"] != user.id` before acting, preventing cross-user reply sending.

5. **Row integrity system** (`app/security/row_integrity.py`) -- HMAC-based row integrity verification on load, with configurable strict mode.

6. **Reminder cancellation authorization** (`app/services/tool_executor.py`, line 196) -- Validates that `job_id` belongs to the requesting user before cancellation.

7. **Encryption at rest** -- Two-layer encryption (Tink AEAD for data columns, Fernet for OAuth tokens) with proper AAD binding.

8. **Rate limiting** -- Consistent Redis-based rate limiting pattern across code execution, web search, and userbot notifications.

9. **HTML escaping** in userbot monitor (`_esc()` function used for sender names and content in notifications).

10. **Password message deletion** (`app/bot/routers/userbot.py`, line 549) -- Attempts to delete the message containing the user's 2FA password after processing.

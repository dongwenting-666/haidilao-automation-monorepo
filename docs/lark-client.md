# Lark Client Library (`libs/lark-client`)

Synchronous Feishu/Lark bot client with automatic token management. Supports messaging (text, cards) and Drive file access.

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| `LARK_APP_ID` | Lark bot application ID (from open.feishu.cn) |
| `LARK_APP_SECRET` | Lark bot application secret |
| **Bot permissions** | `im:message:send_as_bot` — send messages |
| | `drive:drive:readonly` — read Drive files |
| | `drive:file` — upload files to Drive |
| | `contact:user.base:readonly` — read user info (OAuth login) |

---

## Quick Start

```python
from lark_client import LarkClient

with LarkClient(app_id="...", app_secret="...") as client:
    client.send_text("Hello!", chat_id="oc_xxxx")
```

The client auto-refreshes its tenant access token (2-hour TTL, refreshed 5 min early). Thread-safe.

---

## API Reference

### `LarkClient(app_id, app_secret, timeout=30)`

| Method | Description |
|--------|-------------|
| `send_text(text, *, chat_id=None, user_id=None)` | Send plain-text message to a group chat or user |
| `send_card(title, content, *, chat_id=None, user_id=None, color="blue")` | Send an interactive card message (Markdown body) |
| `reply_text(message_id, text)` | Reply to an existing message |
| `send_file(path_or_bytes, filename, *, chat_id=None, user_id=None, file_type="xlsx")` | Upload a file to Lark IM and send as a file message |
| `download_file(file_token)` | Download a Drive file → `bytes` |
| `upload_file(folder_token, filename, data, mime_type=...)` | Upload bytes to a Drive folder |
| `list_folder(folder_token)` | List files in a Drive folder → `list[dict]` |
| `close()` | Close the HTTP client (also called by `__exit__`) |

For `send_text` and `send_card`: provide **exactly one** of `chat_id` (group open_chat_id) or `user_id` (user open_id).

`send_card` color values: `"blue"` | `"green"` | `"red"` | `"yellow"` | `"grey"`.

`list_folder` returns dicts with keys: `name`, `token`, `type`, `created_time`, `modified_time`.

### Errors

| Exception | When |
|-----------|------|
| `LarkAuthError` | Failed to obtain tenant access token |
| `LarkAPIError(code, msg)` | Lark API returned non-zero code |

Both inherit from `LarkError`.

---

## notify.toml — Automatic Run Notifications

The server sends Lark notifications on run completion. Targets are configured in `server/notify.toml`.

Chat IDs are defined **once** in `[chats]` and referenced by name — never hardcode raw IDs in per-command entries:

```toml
# server/notify.toml

[chats]
hongming     = "oc_78f29489a577f10e36ebf989bccdcc83"   # server alerts / error monitoring
store_hours  = "oc_9fe9a845d25c1e07a58a1230cbb04b5d"   # store-hours-collect group
production_accounting_report_chat = "oc_ff2a74b2ba7b07eee95c6138b9cfd112"

[daily-report]
chat = "hongming"         # resolved via [chats]

[store-hours-collect]
chat = "store_hours"

[ksb1]
# chat = "hongming"
```

- `chat = "<alias>"` — preferred; resolved via `[chats]`
- `chat_id = "<raw_id>"` — fallback for direct IDs
- `user_id = "<open_id>"` — DM to a specific user
- Changes to `notify.toml` require a server restart (config is `lru_cache`'d).
- If `LARK_APP_ID` / `LARK_APP_SECRET` are not set, all notifications are silent no-ops.
- If a command has no entry in `notify.toml`, notification is silently skipped.

### Daily Report — XLSX File Delivery

After each successful `daily-report` run, the generated `.xlsx` file is also sent to the `production_accounting_report_chat` chat via `notify_daily_report_file()`. This is in addition to the standard completion card sent to the `daily-report` target chat.

### Notification format

A card is sent on run completion:
- ✅ green card on success, ❌ red card on failure
- Title: `<command> — <status> ⏱ <duration>s`
- Body: last 8 lines of run logs (fenced code block)

### Sending ad-hoc notifications

```python
from server.notify import notify_text, notify_run_complete

notify_text("daily-report", "Custom message")   # uses target from notify.toml
notify_run_complete(run)                          # called automatically after every run
```

---

## Admin OAuth Flow

Lark OAuth is used to authenticate admin users at `/admin/login`.

**Flow:**
1. User visits `/admin/login` → redirected to Lark authorize URL
2. User approves in Lark → callback to `/admin/oauth/callback?code=<code>&state=<state>`
3. Server exchanges code for user info (open_id, name)
4. Server checks `is_whitelisted(open_id)`:
   - DB check first (`admin_users.whitelisted = true`)
   - Fallback: `ADMIN_WHITELIST` env var (comma-separated open_ids)
5. Session cookie set (HMAC-signed, 8-hour TTL)

**Required env vars for OAuth:**

| Variable | Description |
|----------|-------------|
| `LARK_APP_ID` | Bot application ID |
| `LARK_APP_SECRET` | Bot application secret |
| `LARK_OAUTH_REDIRECT_URI` | Must match redirect URI registered in Lark app console |
| `ADMIN_WHITELIST` | Comma-separated Lark open_ids allowed admin access |
| `SESSION_SECRET` | HMAC key for signing session cookies (random key used if unset — sessions don't survive restart) |

Default `LARK_OAUTH_REDIRECT_URI`: `https://haidilao.wanghongming.xyz/admin/oauth/callback`

---

---

## `chat_id_for(alias)` — Named Chat Alias Resolution

All Lark group chat IDs in this monorepo are defined **once** in `server/notify.toml [chats]` and referenced everywhere by name. Never put a raw `oc_xxx` ID in Python code.

```python
from lark_client import chat_id_for

chat_id = chat_id_for("hongming")                        # → "oc_78f29489..."
chat_id = chat_id_for("production_accounting_report_chat")  # → "oc_ff2a74b2..."
chat_id = chat_id_for("nonexistent")                     # → None
```

**Implementation:** `lark_client.notify_config` — reads `server/notify.toml` via `_find_repo_root()`, extracts `[chats]` table, and caches it with `lru_cache(maxsize=1)` for the process lifetime.

**Restart required:** changes to `notify.toml [chats]` only take effect after a process restart (cache is never invalidated at runtime).

**Used by:**
- `server/notify.py` — `_target_for()` resolves per-command `chat = "alias"` entries
- `daily-store-operation-report/main.py` — `_alert_chat_id()` resolves crash/self-test alert target
- `treasury-loan-watch/main.py` — fallback when `TREASURY_NOTIFY_CHAT_ID` env var is not set
- `store-hours-collect/main.py` — fallback when `HOURS_NOTIFY_CHAT_ID` env var is not set

### Bot permissions required for `send_file`

`send_file()` uses the Lark IM file upload API (`/im/v1/files`), which requires an additional bot scope:

| Permission | Scope key | Purpose |
|---|---|---|
| IM file upload | `im:resource` | Required for `send_file()` |

Grant at: **open.feishu.cn → App → Permissions → im:resource**

---

## Module Layout

```
libs/lark-client/
└── src/lark_client/
    ├── __init__.py       # re-exports LarkClient, LarkError hierarchy, chat_id_for
    ├── client.py         # LarkClient implementation
    ├── errors.py         # LarkError, LarkAuthError, LarkAPIError
    └── notify_config.py  # chat_id_for() — reads server/notify.toml [chats]
```

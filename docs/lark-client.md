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

The server sends Lark notifications on run completion. Targets are configured in `server/notify.toml`:

```toml
# server/notify.toml
# Each key is a command name (matches BaseCommand.name).
# Provide either chat_id (group) or user_id (DM), not both.

[daily-report]
chat_id = "oc_ff2a74b2ba7b07eee95c6138b9cfd112"

[ksb1]
# chat_id = "oc_xxxxxxxxxxxxxxxxxxxxxxxx"
# user_id = "ou_xxxxxxxxxxxxxxxxxxxxxxxx"
```

- Changes to `notify.toml` require a server restart (config is `lru_cache`'d).
- If `LARK_APP_ID` / `LARK_APP_SECRET` are not set, all notifications are silent no-ops.
- If a command has no entry in `notify.toml`, notification is silently skipped.

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

## Module Layout

```
libs/lark-client/
└── src/lark_client/
    ├── __init__.py    # re-exports LarkClient, LarkError hierarchy
    ├── client.py      # LarkClient implementation
    └── errors.py      # LarkError, LarkAuthError, LarkAPIError
```

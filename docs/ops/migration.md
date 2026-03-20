# Migrating to a New Mac

This guide covers moving the full Haidilao automation stack to a new Mac mini (or any new macOS machine).

---

## Portability: What's In the Repo vs What Isn't

| Item | In repo? | Portable? | Notes |
|------|----------|-----------|-------|
| Python code, scripts, libs | ✅ | ✅ | Just `git clone` |
| `server/notify.toml` | ✅ | ✅ | Chat aliases — no secrets |
| `docker/docker-compose.yml` | ✅ | ✅ | Service definitions |
| `.env` (secrets) | ❌ | ⚠️ Copy | Never committed — transfer securely |
| `~/Library/LaunchAgents/com.haidilao.server.plist` | ❌ | ⚠️ Copy + edit | Hardcoded paths to `/Users/hongming-claw/` |
| Nginx config | ❌ | ⚠️ Copy | Lives at `/opt/homebrew/etc/nginx/` |
| Docker volumes (Postgres data) | ❌ | ⚠️ Dump/restore | `pg_dump` → transfer → `pg_restore` |
| OpenClaw config | ❌ | ⚠️ Reconfigure | Agent sessions don't transfer |
| CorpLink VPN | ❌ | ❌ Reinstall | App install + IT approval |
| SAP GUI | ❌ | ❌ Reinstall | App install + IT credentials |

**Key hardcoded assumption:** `/Users/hongming-claw/` appears in the plist, `server-start.sh`, and nginx config. Same macOS username = near copy-paste migration. Different username = update ~5 path references.

---

## Step-by-Step Migration

### 1. Prerequisites

Install on the new machine:

```bash
# Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Core tools
brew install uv git nginx cliclick

# Docker Desktop (from docker.com — brew cask is fine too)
brew install --cask docker

# OpenClaw
npm install -g openclaw   # or follow https://docs.openclaw.ai/install

# Python — uv manages this automatically, but ensure Python 3.13+ is available
uv python install 3.13
```

Install separately (require accounts/licenses):
- **CorpLink (FeiLian)** — download from internal IT portal, requires VPN enrollment
- **SAP GUI 8.10** — download from SAP marketplace or internal IT
- **Lark (Feishu)** desktop app — https://www.larksuite.com/download

### 2. Clone the Repo

```bash
git clone git@github.com:HongmingWang-Rabbit/haidilao-automation-monorepo.git
cd haidilao-automation-monorepo
uv sync
```

### 3. Copy Secrets

Transfer `.env` from the old machine **securely** (never email or Slack):

```bash
# On old machine — options:
scp .env newmachine:~/haidilao-automation-monorepo/.env
# or: AirDrop, encrypted USB, 1Password secure share
```

### 4. Start Docker Services

```bash
docker compose -f docker/docker-compose.yml up -d
```

This starts PostgreSQL (`:5432`) and MinIO (`:9000`, `:9001`), both bound to `127.0.0.1` only.

#### Restore Postgres Data (if migrating existing data)

```bash
# On old machine:
pg_dump -h localhost -U haidilao haidilao > haidilao_backup.sql

# On new machine (after docker compose up -d):
psql -h localhost -U haidilao haidilao < haidilao_backup.sql
```

### 5. Install Playwright Browsers

```bash
uv run playwright install chromium
```

### 6. Set Up Nginx

The nginx config is not in the repo. Copy from old machine:

```bash
# On old machine:
scp /opt/homebrew/etc/nginx/sites-enabled/haidilao.conf newmachine:/tmp/

# On new machine:
mkdir -p /opt/homebrew/etc/nginx/sites-enabled
cp /tmp/haidilao.conf /opt/homebrew/etc/nginx/sites-enabled/
brew services start nginx
```

If the domain or IP changes, update `server_name` in the nginx config and update `LARK_OAUTH_REDIRECT_URI` in `.env`.

### 7. Install the LaunchAgent

```bash
# Copy the plist
cp ~/Library/LaunchAgents/com.haidilao.server.plist \
   /path/to/new/machine/Library/LaunchAgents/com.haidilao.server.plist

# If the macOS username changed, update hardcoded paths in the plist:
# Search for: /Users/hongming-claw/
# Replace with: /Users/<new-username>/
```

Also update paths in `scripts/server-start.sh` if the username changed.

```bash
# Load the service
launchctl load ~/Library/LaunchAgents/com.haidilao.server.plist

# Verify
launchctl list com.haidilao.server
curl http://localhost:8000/api/runs
```

### 8. Set Up OpenClaw

```bash
openclaw gateway start
```

Then re-pair any companion apps (iOS/Android) via the OpenClaw QR code or setup code. Sessions and conversation history from the old machine do not transfer — only the config does.

If the public URL changed, update `gateway.remote.url` in `~/.openclaw/openclaw.json`.

### 9. Update Lark App OAuth Redirect URI (if domain changed)

If the server URL changed (e.g. new domain or IP), update the OAuth callback URI:

1. Go to [open.feishu.cn](https://open.feishu.cn) → App `cli_a915e566ba389bd8`
2. **Security** → Redirect URLs → update to new URL
3. Update `LARK_OAUTH_REDIRECT_URI` in `.env`
4. Restart the server: `launchctl stop com.haidilao.server && launchctl start com.haidilao.server`

---

## Post-Migration Verification Checklist

```
[ ] Server responds:       curl http://localhost:8000/api/runs
[ ] Nginx proxy works:     curl https://haidilao.wanghongming.xyz/api/runs
[ ] Lark OAuth works:      visit https://haidilao.wanghongming.xyz/admin
[ ] DB connected:          check server.log for migration messages (no errors)
[ ] VPN connects:          CorpLink shows "Connected"
[ ] QBI accessible:        manually run a quick QBI login check
[ ] Lark notifications:    curl http://localhost:8000/api/commands (should list commands)
[ ] Scheduler running:     curl http://localhost:8000/api/jobs (should show 3 cron jobs)
[ ] LaunchAgent on crash:  kill -9 $(pgrep -f "python3 -m server"); check server.log for crash alert lines
[ ] File send works:       send a test file via notify_daily_report_file()
```

---

## Hardware-Specific Notes

These paths are hardcoded and must be verified on a new machine:

| Item | Current path | Verify with |
|------|-------------|-------------|
| `uv` binary | `/Users/hongming-claw/.local/bin/uv` | `which uv` |
| `openclaw` binary | `/opt/homebrew/bin/openclaw` | `which openclaw` |
| `cliclick` binary | `/opt/homebrew/bin/cliclick` | `which cliclick` |
| SAP GUI app | `/Applications/SAPGUI 8.10.app` | `ls /Applications/SAPGUI*` |
| CorpLink app | `/Applications/CorpLink.app` | `ls /Applications/CorpLink*` |
| CorpLink log | `/usr/local/corplink/logs/corplink.log` | `ls /usr/local/corplink/` |

If any paths differ, update:
- `scripts/server-start.sh` — `uv` and `openclaw` paths
- `~/Library/LaunchAgents/com.haidilao.server.plist` — `uv` path in `ProgramArguments`
- `libs/vpn/src/vpn/_darwin.py` — CorpLink window geometry (may differ on different screen resolutions)
- `libs/sap-gui/` — SAP GUI app path if major version changes

---

## Estimated Migration Time

| Task | Time |
|------|------|
| Prerequisites install | 30–60 min |
| Repo clone + uv sync | 5 min |
| Docker + Postgres restore | 15 min |
| Nginx setup | 10 min |
| LaunchAgent + verify | 10 min |
| OpenClaw re-pair | 10 min |
| Lark OAuth update (if domain changed) | 5 min |
| End-to-end smoke test | 15 min |
| **Total** | **~2 hours** |

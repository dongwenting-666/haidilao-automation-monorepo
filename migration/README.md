# Migration Bundle — Haidilao Automation

## What This Is

Complete migration package for the Haidilao Canada automation system. Contains everything needed to replicate the full production environment on a new Mac.

**Source machine:** Mac mini M1, 8GB RAM, macOS 14.5, user `hongming-claw`

## Contents

| File/Dir | What | Sensitive? |
|----------|------|------------|
| `setup-new-machine.sh` | Automated setup script — run first | No |
| `dot_env` | All secrets: SAP creds, Lark bot, DB password, run token, session secret | **YES** |
| `ssh_keys/` | Ed25519 SSH keypair for GitHub | **YES** |
| `haidilao_db_dump.sql` | Full PostgreSQL database (targets, competitors, travel budgets, users) | Yes |
| `nginx_haidilao.conf` | Nginx reverse proxy config (haidilao.wanghongming.xyz -> localhost:8000) | No |
| `letsencrypt/` | Let's Encrypt SSL certificates + renewal config | Yes |
| `launchagents/` | macOS LaunchAgent plists (server, cron jobs) | No |
| `bi_env.json` | Business intelligent repo machine-specific config | No |
| `brew_packages.txt` | Homebrew package list | No |
| `claude_dot_json` | Claude Code auth + project config | Yes |
| `claude_settings.json` | Claude Code settings (hooks, permissions) | No |
| `haidilao-business-intelligent/` | Claude Code orchestration repo (memory, prompts, MCP server) | No |

---

## For AI Agent: Full Setup Instructions

Paste this entire README into Claude Code on the new machine. The AI agent can execute everything except macOS permission dialogs.

### Step 1: Run the setup script

```bash
cd ~/migration-bundle
chmod +x setup-new-machine.sh
./setup-new-machine.sh
```

This handles: Homebrew, SSH keys, git clone, .env, Python/Node deps, LaunchAgents, Claude Code, git config.

### Step 2: Docker Desktop

```bash
# Download Docker Desktop for Apple Silicon
curl -L -o ~/Downloads/Docker.dmg "https://desktop.docker.com/mac/main/arm64/Docker.dmg"
# Mount and install
hdiutil attach ~/Downloads/Docker.dmg
cp -R "/Volumes/Docker/Docker.app" /Applications/
hdiutil detach "/Volumes/Docker"
# Launch Docker (first launch requires user click to accept terms)
open /Applications/Docker.app
```

After Docker is running:

```bash
cd ~/haidilao-automation-monorepo/docker
docker compose up -d
# Wait for PostgreSQL
sleep 15
# Restore database
docker exec -i haidilao-postgres psql -U haidilao haidilao < ~/migration-bundle/haidilao_db_dump.sql
```

### Step 3: DNS Update

If the machine's public IP changed:

```bash
# Check current public IP
curl -s ifconfig.me
# Old IP was: 174.7.5.145
# Update the A record for haidilao.wanghongming.xyz at your DNS provider
```

Also update port forwarding on the router: forward ports 80 and 443 to the new machine's LAN IP.

```bash
# Find LAN IP
ipconfig getifaddr en0
```

### Step 4: SSL Certificates

```bash
# Option A: Restore existing certs
sudo mkdir -p /etc/letsencrypt
sudo cp -r ~/migration-bundle/letsencrypt/* /etc/letsencrypt/

# Option B: Issue fresh certs (if DNS already points to new IP)
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot -w /var/www/certbot -d haidilao.wanghongming.xyz
```

Set up auto-renewal:

```bash
sudo tee /Library/LaunchDaemons/org.certbot.renew.plist << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>org.certbot.renew</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/certbot</string>
        <string>renew</string>
        <string>--quiet</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>
</dict>
</plist>
PLIST
sudo launchctl bootstrap system /Library/LaunchDaemons/org.certbot.renew.plist
```

### Step 5: Nginx

```bash
brew services start nginx
nginx -t
# Verify proxy config
grep "proxy_pass" /opt/homebrew/etc/nginx/sites-enabled/haidilao.conf
```

### Step 6: SAP GUI

Download SAP GUI for Mac from SAP's website (requires SAP login). After install:

```bash
# Verify
ls /Applications/SAP\ Clients/
# Enable scripting: SAP GUI → Settings → Accessibility → Enable Scripting
```

### Step 7: CorpLink VPN

Install CorpLink from the company portal. Verify automation tools:

```bash
which cliclick || brew install cliclick
```

### Step 8: macOS Permissions

**These MUST be done manually via System Settings UI:**

Open **System Settings -> Privacy & Security** and add **Terminal.app** to:

- [ ] Full Disk Access
- [ ] Accessibility
- [ ] Local Network

### Step 9: GitHub CLI

```bash
gh auth login
# Choose: GitHub.com -> HTTPS -> Login with browser
```

### Step 10: Verify Everything

```bash
# Server running?
launchctl start com.haidilao.server
sleep 5
RUN_TOKEN=$(grep RUN_TOKEN ~/haidilao-automation-monorepo/.env | cut -d= -f2)
curl -sf -H "X-Run-Token: $RUN_TOKEN" http://localhost:8000/api/runs && echo " OK"

# Docker containers?
docker ps --format '{{.Names}} {{.Status}}'

# Cron jobs?
launchctl list | grep com.haidilao

# VPN?
cd ~/haidilao-automation-monorepo
uv run --project server python -c "from vpn.connect import ensure_vpn; ensure_vpn()"

# Admin panel?
open https://haidilao.wanghongming.xyz/admin/

# Test daily report (skip-download for quick test)?
curl -s -X POST -H "X-Run-Token: $RUN_TOKEN" http://localhost:8000/api/jobs/daily-report-cron/trigger
```

---

## Architecture

```
Mac (new machine)
|-- haidilao-automation-monorepo/     <- Main Python monorepo (git)
|   |-- server/ (FastAPI, port 8000)  <- LaunchAgent: com.haidilao.server
|   |-- projects/                     <- 6 automation projects
|   |-- libs/                         <- Shared libraries (SAP, QBI, VPN, Lark)
|   +-- docker/                       <- PostgreSQL + MinIO
|-- haidilao-business-intelligent/    <- Claude Code orchestration
|   |-- prompts/                      <- Cron job prompts
|   |-- memory/                       <- Persistent memory
|   +-- src/server.ts                 <- MCP tools server
|-- nginx -> localhost:8000           <- Reverse proxy + SSL
+-- LaunchAgents                      <- Auto-start + cron jobs
    |-- com.haidilao.server
    |-- com.haidilao.claude.health-check   (every 1h)
    |-- com.haidilao.claude.log-monitor    (every 30m)
    +-- com.haidilao.claude.memory-compactor (every 6h)
```

## Rollback

If something goes wrong on the new machine, the old machine is unchanged. Just point DNS back to the old IP.

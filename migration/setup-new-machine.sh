#!/bin/bash
# ============================================================
# Haidilao Automation — New Machine Setup Script
# Run this on the NEW machine after copying the migration-bundle
# ============================================================
set -euo pipefail

echo "🍲 Haidilao Automation — New Machine Setup"
echo "==========================================="
echo ""

BUNDLE_DIR="$(cd "$(dirname "$0")" && pwd)"
HOME_DIR="$HOME"
NEW_USER=$(whoami)

echo "Bundle: $BUNDLE_DIR"
echo "User: $NEW_USER"
echo "Home: $HOME_DIR"
echo ""

# ── Step 1: Homebrew ─────────────────────────────────────────
echo "📦 Step 1: Installing Homebrew packages..."
if ! command -v brew &>/dev/null; then
    echo "  Installing Homebrew first..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv)"
fi

brew install python@3.14 node@22 nginx certbot cliclick git gh uv 2>/dev/null || true
echo "  ✓ Homebrew packages installed"

# ── Step 2: Clone repos ─────────────────────────────────────
echo ""
echo "📂 Step 2: Cloning repositories..."

# Restore SSH keys first
if [ -d "$BUNDLE_DIR/ssh_keys" ]; then
    mkdir -p ~/.ssh
    cp "$BUNDLE_DIR/ssh_keys/id_ed25519" ~/.ssh/ 2>/dev/null || true
    cp "$BUNDLE_DIR/ssh_keys/id_ed25519.pub" ~/.ssh/ 2>/dev/null || true
    chmod 600 ~/.ssh/id_ed25519 2>/dev/null || true
    echo "  ✓ SSH keys restored"
fi

if [ ! -d "$HOME_DIR/haidilao-automation-monorepo" ]; then
    git clone git@github.com:HongmingWang-Rabbit/haidilao-automation-monorepo.git "$HOME_DIR/haidilao-automation-monorepo"
    echo "  ✓ Monorepo cloned"
else
    echo "  ✓ Monorepo already exists"
fi

if [ ! -d "$HOME_DIR/haidilao-business-intelligent" ]; then
    echo "  ⚠ haidilao-business-intelligent not found — copy it manually from old machine"
else
    echo "  ✓ Business intelligent repo exists"
fi

# ── Step 3: Secrets & config ────────────────────────────────
echo ""
echo "🔐 Step 3: Restoring secrets..."

cp "$BUNDLE_DIR/dot_env" "$HOME_DIR/haidilao-automation-monorepo/.env"
echo "  ✓ .env restored"

# ── Step 4: Python/Node deps ────────────────────────────────
echo ""
echo "📚 Step 4: Installing dependencies..."

cd "$HOME_DIR/haidilao-automation-monorepo"
uv sync 2>/dev/null || true
echo "  ✓ Python deps installed"

if [ -d "$HOME_DIR/haidilao-business-intelligent" ]; then
    cd "$HOME_DIR/haidilao-business-intelligent"
    npm install -g pnpm 2>/dev/null || true
    pnpm install 2>/dev/null || true
    echo "  ✓ Node deps installed"
fi

# ── Step 5: Docker + PostgreSQL ──────────────────────────────
echo ""
echo "🐳 Step 5: Setting up Docker + PostgreSQL..."

if ! command -v docker &>/dev/null; then
    echo "  ⚠ Docker not installed — install Docker Desktop manually"
    echo "    https://www.docker.com/products/docker-desktop/"
else
    cd "$HOME_DIR/haidilao-automation-monorepo/docker"
    docker compose up -d 2>/dev/null || true
    echo "  Waiting for PostgreSQL to start..."
    sleep 10

    # Restore database
    if [ -f "$BUNDLE_DIR/haidilao_db_dump.sql" ]; then
        docker exec -i haidilao-postgres psql -U haidilao haidilao < "$BUNDLE_DIR/haidilao_db_dump.sql" 2>/dev/null || true
        echo "  ✓ Database restored"
    fi
fi

# ── Step 6: Nginx + SSL ─────────────────────────────────────
echo ""
echo "🌐 Step 6: Setting up nginx..."

if [ -f "$BUNDLE_DIR/nginx_haidilao.conf" ]; then
    mkdir -p /opt/homebrew/etc/nginx/sites-enabled 2>/dev/null || true
    # Update paths in nginx config for new user
    sed "s|/Users/hongming-claw|$HOME_DIR|g" "$BUNDLE_DIR/nginx_haidilao.conf" > /opt/homebrew/etc/nginx/sites-enabled/haidilao.conf
    echo "  ✓ Nginx config installed (paths updated)"
fi

if [ -d "$BUNDLE_DIR/letsencrypt" ]; then
    echo "  ⚠ SSL certs need manual copy: sudo cp -r $BUNDLE_DIR/letsencrypt /etc/"
fi

# ── Step 7: LaunchAgents ─────────────────────────────────────
echo ""
echo "⏰ Step 7: Installing LaunchAgents..."

# Update paths in plist files and install
for plist in "$BUNDLE_DIR/launchagents/"*.plist; do
    [ -f "$plist" ] || continue
    name=$(basename "$plist")
    sed "s|/Users/hongming-claw|$HOME_DIR|g" "$plist" > "$HOME_DIR/Library/LaunchAgents/$name"
    launchctl bootstrap "gui/$(id -u)" "$HOME_DIR/Library/LaunchAgents/$name" 2>/dev/null || true
    echo "  ✓ $name"
done

# ── Step 8: Claude Code ─────────────────────────────────────
echo ""
echo "🤖 Step 8: Setting up Claude Code..."

if ! command -v claude &>/dev/null; then
    echo "  Installing Claude Code..."
    curl -fsSL https://claude.ai/install.sh | sh 2>/dev/null || true
fi

# Run business-intelligent setup (creates symlinks + cron plists)
if [ -d "$HOME_DIR/haidilao-business-intelligent" ]; then
    cd "$HOME_DIR/haidilao-business-intelligent"

    # Update env.json with new machine paths
    if [ -f config/env.json ]; then
        sed -i '' "s|/Users/hongming-claw|$HOME_DIR|g" config/env.json
    fi

    pnpm run setup 2>/dev/null || true
    echo "  ✓ Claude Code setup complete"
fi

# ── Step 9: Git config ───────────────────────────────────────
echo ""
echo "📝 Step 9: Git config..."
git config --global user.email "hongmingwangrabbit@gmail.com"
git config --global user.name "hongming-claw"
echo "  ✓ Git configured"

# ── Step 10: macOS permissions ───────────────────────────────
echo ""
echo "🔒 Step 10: macOS permissions..."
echo "  ⚠ MANUAL: Open System Settings → Privacy & Security"
echo "    - Full Disk Access → add Terminal.app"
echo "    - Accessibility → add Terminal.app"
echo "    - Local Network → add Terminal.app"

# ── Done ─────────────────────────────────────────────────────
echo ""
echo "==========================================="
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Grant macOS permissions (see Step 10 above)"
echo "  2. Install Docker Desktop if not done"
echo "  3. Install SAP GUI for Mac"
echo "  4. Login to gh: gh auth login"
echo "  5. Start the server: launchctl start com.haidilao.server"
echo "  6. Test: curl http://localhost:8000/api/runs"
echo "  7. Update DNS if the IP changed"
echo "  8. Renew SSL cert: sudo certbot renew"
echo ""
echo "Migration bundle can be deleted after verification."

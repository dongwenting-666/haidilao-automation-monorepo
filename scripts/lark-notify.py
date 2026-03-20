#!/usr/bin/env python3
"""Send a plain-text Lark message to a named chat alias.

Usage:
    uv run --project server python scripts/lark-notify.py <alias> <message>

Example:
    uv run --project server python scripts/lark-notify.py hongming "Server recovered. Crash was caused by OOM."

The alias must exist in server/notify.toml [chats].
"""
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
os.chdir(repo_root)

from dotenv import load_dotenv
load_dotenv(repo_root / ".env")

if len(sys.argv) < 3:
    print(f"Usage: {sys.argv[0]} <chat_alias> <message>", file=sys.stderr)
    sys.exit(1)

alias = sys.argv[1]
message = " ".join(sys.argv[2:])

from lark_client import LarkClient, chat_id_for

app_id = os.environ.get("LARK_APP_ID", "")
app_secret = os.environ.get("LARK_APP_SECRET", "")
chat_id = chat_id_for(alias)

if not app_id or not app_secret:
    print("ERROR: LARK_APP_ID / LARK_APP_SECRET not set", file=sys.stderr)
    sys.exit(1)
if not chat_id:
    print(f"ERROR: alias '{alias}' not found in notify.toml [chats]", file=sys.stderr)
    sys.exit(1)

with LarkClient(app_id=app_id, app_secret=app_secret) as client:
    client.send_text(message, chat_id=chat_id)

print(f"Sent to '{alias}' ({chat_id})")

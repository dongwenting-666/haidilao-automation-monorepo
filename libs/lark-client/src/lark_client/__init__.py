"""Feishu/Lark bot client.

Usage:
    from lark_client import LarkClient

    client = LarkClient(app_id="...", app_secret="...")

    # Send a text message to a chat (resolve chat_id via chat_id_for("alias"))
    client.send_text(chat_id=chat_id_for("hongming"), text="Hello!")

    # Send a rich card message
    client.send_card(chat_id=chat_id_for("hongming"), title="Report ready", content="...")

    # Download a Drive file
    data = client.download_file(file_token="xxx")
"""

from __future__ import annotations

from lark_client.client import LarkClient
from lark_client.errors import LarkError, LarkAuthError, LarkAPIError
from lark_client.notify_config import chat_id_for

__all__ = ["LarkClient", "LarkError", "LarkAuthError", "LarkAPIError", "chat_id_for"]

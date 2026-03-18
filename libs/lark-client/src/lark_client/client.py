"""Feishu/Lark bot client — synchronous, token-caching."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from lark_client.errors import LarkAPIError, LarkAuthError

log = logging.getLogger(__name__)

_BASE = "https://open.feishu.cn/open-apis"
# Tenant access tokens expire after 2 hours; refresh 5 min early.
_TOKEN_TTL_BUFFER = 300


class LarkClient:
    """Synchronous Feishu/Lark bot client with automatic token management.

    Parameters
    ----------
    app_id:
        The bot application ID from open.feishu.cn.
    app_secret:
        The bot application secret.
    timeout:
        HTTP request timeout in seconds (default 30).
    """

    def __init__(self, app_id: str, app_secret: str, timeout: float = 30.0) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._http = httpx.Client(timeout=timeout)
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        """Return a valid tenant access token, refreshing if needed."""
        with self._lock:
            if self._token and time.monotonic() < self._token_expires_at:
                return self._token

            resp = self._http.post(
                f"{_BASE}/auth/v3/tenant_access_token/internal",
                json={"app_id": self._app_id, "app_secret": self._app_secret},
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                raise LarkAuthError(
                    f"Failed to get tenant access token: {data.get('msg')}"
                )

            self._token = data["tenant_access_token"]
            self._token_expires_at = (
                time.monotonic() + data.get("expire", 7200) - _TOKEN_TTL_BUFFER
            )
            return self._token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}"}

    def _post(self, path: str, json: Any) -> dict:
        """POST to a Lark API endpoint, raise on non-zero code."""
        resp = self._http.post(
            f"{_BASE}{path}",
            headers=self._headers(),
            json=json,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise LarkAPIError(data.get("code", -1), data.get("msg", "unknown error"))
        return data

    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        """GET from a Lark API endpoint (raw response, caller checks status)."""
        resp = self._http.get(
            f"{_BASE}{path}",
            headers=self._headers(),
            params=params,
        )
        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    def send_text(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        """Send a plain-text message to a chat or user.

        Provide exactly one of *chat_id* (group/direct chat open_chat_id)
        or *user_id* (user's open_id).
        """
        receive_id, id_type = _resolve_target(chat_id, user_id)
        return self._post(
            f"/im/v1/messages?receive_id_type={id_type}",
            {
                "receive_id": receive_id,
                "msg_type": "text",
                "content": f'{{"text": {_json_str(text)}}}',
            },
        )

    def send_card(
        self,
        title: str,
        content: str,
        *,
        chat_id: str | None = None,
        user_id: str | None = None,
        color: str = "blue",
    ) -> dict:
        """Send an interactive card message.

        Parameters
        ----------
        title:
            Card header text.
        content:
            Markdown-formatted body text.
        color:
            Header colour: "blue" | "green" | "red" | "yellow" | "grey".
        """
        receive_id, id_type = _resolve_target(chat_id, user_id)
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": color,
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": content},
                }
            ],
        }
        import json
        return self._post(
            f"/im/v1/messages?receive_id_type={id_type}",
            {
                "receive_id": receive_id,
                "msg_type": "interactive",
                "content": json.dumps(card),
            },
        )

    def reply_text(self, message_id: str, text: str) -> dict:
        """Reply to an existing message."""
        return self._post(
            f"/im/v1/messages/{message_id}/reply",
            {
                "msg_type": "text",
                "content": f'{{"text": {_json_str(text)}}}',
            },
        )

    # ------------------------------------------------------------------
    # Drive / file access
    # ------------------------------------------------------------------

    def get_file_meta(self, file_token: str, file_type: str = "file") -> dict:
        """Get metadata for a Drive file.

        Parameters
        ----------
        file_token:
            The file token (from a Feishu Drive link).
        file_type:
            "file" for regular files, "docx" for documents, "sheet" for
            spreadsheets, etc.
        """
        resp = self._get(
            f"/drive/v1/metas/batch_query",
            params=None,
        )
        # Use the single-file meta endpoint instead
        data = self._get(
            f"/drive/v1/files/{file_token}",
            params={"type": file_type},
        ).json()
        if data.get("code") != 0:
            raise LarkAPIError(data.get("code", -1), data.get("msg", "unknown"))
        return data.get("data", {})

    def download_file(self, file_token: str) -> bytes:
        """Download a Drive file and return its raw bytes.

        The bot must have at least read permission on the file.
        """
        resp = self._get(f"/drive/v1/files/{file_token}/download")
        return resp.content

    def list_folder(self, folder_token: str) -> list[dict]:
        """List files in a Drive folder.

        Returns a list of file metadata dicts with keys:
        name, token, type, created_time, modified_time.
        """
        items: list[dict] = []
        page_token: str | None = None

        while True:
            params: dict = {"folder_token": folder_token, "page_size": 200}
            if page_token:
                params["page_token"] = page_token

            data = self._get("/drive/v1/files", params=params).json()
            if data.get("code") != 0:
                raise LarkAPIError(data.get("code", -1), data.get("msg", "unknown"))

            items.extend(data.get("data", {}).get("files", []))

            if not data.get("data", {}).get("has_more"):
                break
            page_token = data["data"].get("next_page_token")

        return items

    def upload_file(
        self,
        folder_token: str,
        filename: str,
        data: bytes,
        mime_type: str = "application/octet-stream",
    ) -> dict:
        """Upload a file to a Drive folder.

        Returns the created file metadata.
        """
        import io
        token = self._get_token()
        resp = self._http.post(
            f"{_BASE}/drive/v1/files/upload_all",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "file_name": filename,
                "parent_type": "explorer",
                "parent_node": folder_token,
                "size": str(len(data)),
            },
            files={"file": (filename, io.BytesIO(data), mime_type)},
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") != 0:
            raise LarkAPIError(result.get("code", -1), result.get("msg", "unknown"))
        return result.get("data", {})

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> "LarkClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _resolve_target(
    chat_id: str | None, user_id: str | None
) -> tuple[str, str]:
    """Return (receive_id, id_type) from exactly one of chat_id or user_id."""
    if chat_id and user_id:
        raise ValueError("Provide chat_id or user_id, not both")
    if chat_id:
        return chat_id, "chat_id"
    if user_id:
        return user_id, "open_id"
    raise ValueError("Provide either chat_id or user_id")


def _json_str(text: str) -> str:
    """JSON-encode a string value (including the surrounding quotes)."""
    import json
    return json.dumps(text)

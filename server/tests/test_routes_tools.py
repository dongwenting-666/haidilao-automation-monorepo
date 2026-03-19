"""Tests for the Admin Tools routes (MinIO file storage).

Coverage:
- Unauthenticated access → redirect to login
- Non-localhost access to agent endpoint → 403
- Authenticated super-admin upload/list/delete (MinIO mocked)
- Agent endpoint from localhost (MinIO mocked)
"""

from __future__ import annotations

import asyncio
import io
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure SESSION_SECRET is stable for the entire test module so that
# cookies signed in helpers are valid when verified by the server.
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-pytest-tools-1234")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session_cookie(open_id: str = "ou_testuser", name: str = "Test User") -> dict:
    """Return a cookies dict with a valid signed session cookie."""
    # Import after env is set
    from server.auth import _get_signer
    import json

    payload = json.dumps({"open_id": open_id, "name": name})
    signed = _get_signer().sign(payload).decode()
    return {"admin_session": signed}


def _mock_minio_client(bucket_exists: bool = True, objects=None):
    """Return a mock MinIO client that passes bucket checks."""
    mock = MagicMock()
    mock.bucket_exists.return_value = bucket_exists
    mock.make_bucket.return_value = None
    mock.list_objects.return_value = iter(objects if objects is not None else [])
    return mock


# ── Unauthenticated access ────────────────────────────────────────────────────

class TestUnauthenticated:
    def test_get_tools_page_redirects_to_login(self, client: TestClient):
        resp = client.get("/admin/tools/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["location"]

    def test_post_upload_redirects_to_login(self, client: TestClient):
        resp = client.post(
            "/admin/tools/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["location"]

    def test_get_files_list_redirects_to_login(self, client: TestClient):
        resp = client.get("/admin/tools/files", follow_redirects=False)
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["location"]

    def test_delete_file_redirects_to_login(self, client: TestClient):
        resp = client.delete("/admin/tools/files/some-key", follow_redirects=False)
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["location"]


# ── Agent endpoint: non-localhost → 403 ──────────────────────────────────────

class TestAgentEndpoint:
    """Test the /api/tools/agent/{key} localhost-only endpoint."""

    def test_agent_endpoint_from_non_localhost_returns_403(self):
        """Non-localhost IPs must receive 403 regardless of MinIO state."""
        from fastapi import HTTPException
        from server.routes.tools import agent_download

        for host in ("192.168.1.1", "10.0.0.1", "8.8.8.8", "2001:db8::1"):
            mock_request = MagicMock()
            mock_request.client.host = host
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(agent_download("some-key", mock_request))
            assert exc_info.value.status_code == 403, f"Expected 403 for host {host}"

    def test_agent_endpoint_localhost_allowed_when_minio_works(self):
        """Requests from 127.0.0.1 should pass the IP check and serve the file."""
        from server.routes.tools import agent_download

        mock_data = b"file content here"
        mock_stat = MagicMock()
        mock_stat.content_type = "text/plain"
        mock_stat.size = len(mock_data)

        mock_minio_resp = MagicMock()
        mock_minio_resp.read.return_value = mock_data
        mock_minio_resp.close.return_value = None
        mock_minio_resp.release_conn.return_value = None

        mock_mc = _mock_minio_client()
        mock_mc.stat_object.return_value = mock_stat
        mock_mc.get_object.return_value = mock_minio_resp

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"

        with patch("server.routes.tools._get_minio_client", return_value=mock_mc):
            resp = asyncio.run(agent_download("some-uuid_test.txt", mock_request))

        # Should return a StreamingResponse
        from fastapi.responses import StreamingResponse
        assert isinstance(resp, StreamingResponse)

    def test_agent_endpoint_ipv6_localhost_allowed(self):
        """::1 (IPv6 localhost) should also be allowed."""
        from server.routes.tools import agent_download

        mock_data = b"content"
        mock_stat = MagicMock()
        mock_stat.content_type = "text/plain"
        mock_stat.size = len(mock_data)

        mock_minio_resp = MagicMock()
        mock_minio_resp.read.return_value = mock_data
        mock_minio_resp.close.return_value = None
        mock_minio_resp.release_conn.return_value = None

        mock_mc = _mock_minio_client()
        mock_mc.stat_object.return_value = mock_stat
        mock_mc.get_object.return_value = mock_minio_resp

        mock_request = MagicMock()
        mock_request.client.host = "::1"

        with patch("server.routes.tools._get_minio_client", return_value=mock_mc):
            from fastapi.responses import StreamingResponse
            resp = asyncio.run(agent_download("some-key", mock_request))
            assert isinstance(resp, StreamingResponse)


# ── Super-admin authenticated routes (MinIO mocked) ──────────────────────────

class TestSuperAdminRoutes:
    """Tests with a valid super-admin session and mocked MinIO."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """Patch is_super_admin to return True for all tests in this class."""
        with patch("server.routes.tools.is_super_admin", return_value=True):
            yield

    @property
    def cookies(self) -> dict:
        return _make_session_cookie(open_id="ou_superadmin_test", name="Super Admin")

    def test_tools_page_returns_html(self, client: TestClient):
        resp = client.get("/admin/tools/", cookies=self.cookies)
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "工具" in resp.text
        assert "file-input" in resp.text

    def test_upload_file_success(self, client: TestClient):
        mock_mc = _mock_minio_client()
        mock_mc.put_object.return_value = MagicMock()

        with patch("server.routes.tools._get_minio_client", return_value=mock_mc):
            resp = client.post(
                "/admin/tools/upload",
                files={"file": ("hello.txt", b"hello world", "text/plain")},
                cookies=self.cookies,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["filename"] == "hello.txt"
        assert "hello.txt" in data["key"]
        assert data["size"] == len(b"hello world")
        assert data["agent_url"].startswith("http://localhost:8000/api/tools/agent/")

    def test_list_files_empty(self, client: TestClient):
        with patch("server.routes.tools._get_minio_client", return_value=_mock_minio_client()):
            resp = client.get("/admin/tools/files", cookies=self.cookies)

        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_files_with_objects(self, client: TestClient):
        obj = MagicMock()
        obj.object_name = "abc123_report.xlsx"
        obj.size = 2048
        obj.last_modified = datetime(2026, 3, 19, 10, 0, 0, tzinfo=timezone.utc)

        mock_mc = _mock_minio_client(objects=[obj])
        with patch("server.routes.tools._get_minio_client", return_value=mock_mc):
            resp = client.get("/admin/tools/files", cookies=self.cookies)

        assert resp.status_code == 200
        files = resp.json()
        assert len(files) == 1
        f = files[0]
        assert f["key"] == "abc123_report.xlsx"
        assert f["filename"] == "abc123_report.xlsx"
        assert f["size"] == 2048
        assert "agent_url" in f
        assert f["agent_url"].startswith("http://localhost:8000/api/tools/agent/")

    def test_delete_file_success(self, client: TestClient):
        mock_mc = _mock_minio_client()
        mock_mc.remove_object.return_value = None

        with patch("server.routes.tools._get_minio_client", return_value=mock_mc):
            resp = client.delete(
                "/admin/tools/files/some-key",
                cookies=self.cookies,
            )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_download_file_success(self, client: TestClient):
        content = b"PDF content here"
        mock_stat = MagicMock()
        mock_stat.content_type = "application/pdf"
        mock_stat.size = len(content)

        mock_minio_resp = MagicMock()
        mock_minio_resp.read.return_value = content
        mock_minio_resp.close.return_value = None
        mock_minio_resp.release_conn.return_value = None

        mock_mc = _mock_minio_client()
        mock_mc.stat_object.return_value = mock_stat
        mock_mc.get_object.return_value = mock_minio_resp

        with patch("server.routes.tools._get_minio_client", return_value=mock_mc):
            resp = client.get(
                "/admin/tools/files/some-uuid_document.pdf",
                cookies=self.cookies,
            )

        assert resp.status_code == 200
        assert resp.content == content

    def test_minio_unavailable_returns_503(self, client: TestClient):
        from fastapi import HTTPException

        with patch(
            "server.routes.tools._get_minio_client",
            side_effect=HTTPException(status_code=503, detail="MinIO unavailable"),
        ):
            resp = client.get("/admin/tools/files", cookies=self.cookies)

        assert resp.status_code == 503


# ── Non-super-admin gets 403 ──────────────────────────────────────────────────

class TestNonSuperAdmin:
    def test_tools_page_requires_super_admin(self, client: TestClient):
        """Authenticated non-super-admin users should receive 403."""
        cookies = _make_session_cookie(open_id="ou_regular_user", name="Regular User")
        with patch("server.routes.tools.is_super_admin", return_value=False):
            resp = client.get("/admin/tools/", cookies=cookies, follow_redirects=False)
        # super admin check raises 403, which the app returns (not a redirect)
        assert resp.status_code == 403

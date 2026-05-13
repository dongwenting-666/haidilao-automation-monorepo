"""Tests for /admin/bom routes — wires DB CRUD to JSON endpoints."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_db():
    """Mark DB-connect already-attempted so get_db() returns None without
    trying a real connection (avoids 30s pool timeout in tests). Individual
    tests that want a working DB call _install_mock_db().
    """
    import server.db as db_mod
    db_mod._db = None
    db_mod._db_attempted = True
    yield
    db_mod._db = None
    db_mod._db_attempted = True


@pytest.fixture()
def client_with_session():
    """TestClient that bypasses require_auth (injects a fake session)."""
    from server.app import app
    from server.auth import require_auth

    async def _fake_auth():
        return {"open_id": "test-user", "name": "tester"}

    app.dependency_overrides[require_auth] = _fake_auth
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(require_auth, None)


def _install_mock_db():
    import server.db as db_mod
    mock = MagicMock()
    db_mod._db = mock
    db_mod._db_attempted = True
    return mock


def test_bom_page_renders_empty_when_no_db(client_with_session):
    """Page must still render (with DB warning) when DATABASE_URL is missing."""
    r = client_with_session.get("/admin/bom")
    assert r.status_code == 200
    assert "用料配方" in r.text
    # 'bom' nav link is active on this page
    assert 'class="active"' in r.text or "DATABASE_URL" in r.text


def test_bom_page_lists_rows(client_with_session):
    db = _install_mock_db()
    # When ?werks=CA08 is provided, list_bom_werks() is NOT called (the
    # query param short-circuits the lookup). Only list_bom() runs.
    db.fetchall.return_value = [{
        "id": 1, "werks": "CA08", "dish_code": 1060061,
        "dish_name": "清油麻辣火锅", "dish_short_code": None,
        "spec": "单锅", "material_code": 3000759,
        "material_name": "清油底料", "portion": 1.2,
        "loss_factor": 1.0, "unit": "公斤",
        "packaging_factor": None, "notes": None,
        "created_at": None, "updated_at": None, "created_by": "",
    }]
    db.fetchone.return_value = {"n": 1}  # count_bom

    r = client_with_session.get("/admin/bom?werks=CA08")
    assert r.status_code == 200
    assert "清油麻辣火锅" in r.text
    assert "1060061" in r.text
    assert "3000759" in r.text


def test_bom_save_insert(client_with_session):
    db = _install_mock_db()
    db.fetchone.return_value = {"id": 42}
    r = client_with_session.post(
        "/admin/bom/save",
        json={
            "werks": "CA08", "dish_code": 1060061, "spec": "单锅",
            "material_code": 3000759, "dish_name": "清油麻辣火锅",
            "portion": 1.2, "loss_factor": 1.0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "id": 42}
    # SQL hit the INSERT … ON CONFLICT path (no entry_id given).
    sql = db.fetchone.call_args[0][0]
    assert "INSERT INTO store_bom" in sql


def test_bom_save_update(client_with_session):
    db = _install_mock_db()
    db.fetchone.return_value = {"id": 7}
    r = client_with_session.post(
        "/admin/bom/save",
        json={
            "entry_id": 7,
            "werks": "CA08", "dish_code": 1060061, "spec": "单锅",
            "material_code": 3000759, "portion": 2.0,
        },
    )
    assert r.status_code == 200
    sql = db.fetchone.call_args[0][0]
    assert sql.lstrip().startswith("UPDATE store_bom")


def test_bom_save_no_db_503(client_with_session):
    # No DB installed; is_db_available() returns False.
    r = client_with_session.post(
        "/admin/bom/save",
        json={"werks": "CA08", "dish_code": 1, "material_code": 1},
    )
    assert r.status_code == 503


def test_bom_delete_ok(client_with_session):
    db = _install_mock_db()
    db.fetchone.return_value = {"id": 5}
    r = client_with_session.post("/admin/bom/delete", json={"entry_id": 5})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_bom_delete_missing_404(client_with_session):
    db = _install_mock_db()
    db.fetchone.return_value = None
    r = client_with_session.post("/admin/bom/delete", json={"entry_id": 999})
    assert r.status_code == 404


def test_bom_get_entry(client_with_session):
    db = _install_mock_db()
    db.fetchone.return_value = {
        "id": 5, "werks": "CA08", "dish_code": 1060061,
        "spec": "单锅", "material_code": 3000759,
        "dish_name": "清油麻辣火锅", "dish_short_code": None,
        "material_name": "清油底料", "portion": 1.2,
        "loss_factor": 1.0, "unit": "公斤",
        "packaging_factor": None, "notes": None,
        "created_at": None, "updated_at": None, "created_by": "",
    }
    r = client_with_session.get("/admin/bom/get?id=5")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["entry"]["dish_code"] == 1060061
    assert j["entry"]["material_code"] == 3000759


def test_bom_get_missing_404(client_with_session):
    db = _install_mock_db()
    db.fetchone.return_value = None
    r = client_with_session.get("/admin/bom/get?id=999")
    assert r.status_code == 404

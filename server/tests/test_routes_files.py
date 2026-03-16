"""Tests for server.routes.files — _safe_path, list_files, download_file."""

import pytest
from fastapi import HTTPException


def test_safe_path_valid(tmp_output):
    from server.routes.files import _safe_path

    p = _safe_path("subdir")
    assert p == tmp_output / "subdir"


def test_safe_path_traversal_rejected(tmp_output):
    from server.routes.files import _safe_path

    with pytest.raises(HTTPException) as exc_info:
        _safe_path("../../etc/passwd")
    assert exc_info.value.status_code == 400


def test_list_files_root(client, tmp_output):
    resp = client.get("/api/files/")
    assert resp.status_code == 200
    data = resp.json()
    names = {f["name"] for f in data}
    assert "report.xlsx" in names
    assert "subdir" in names
    # Check shape
    for item in data:
        assert "name" in item
        assert "path" in item
        assert "is_dir" in item


def test_list_files_subdir(client, tmp_output):
    resp = client.get("/api/files/", params={"subdir": "subdir"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "hello.txt"


def test_list_files_missing_dir(client, tmp_output):
    resp = client.get("/api/files/", params={"subdir": "nope"})
    assert resp.status_code == 404


def test_download_file(client, tmp_output):
    resp = client.get("/api/files/report.xlsx")
    assert resp.status_code == 200
    assert resp.content == b"fake-excel"


def test_download_file_in_subdir(client, tmp_output):
    resp = client.get("/api/files/subdir/hello.txt")
    assert resp.status_code == 200
    assert resp.content == b"hello world"


def test_download_file_not_found(client, tmp_output):
    resp = client.get("/api/files/missing.txt")
    assert resp.status_code == 404

"""Unit tests for sap_fiori_crawler.auth — pure helpers only."""
from __future__ import annotations

import json

import pytest

from sap_fiori_crawler import (
    DEFAULT_CLIENT,
    FioriLoginError,
    StoreCreds,
    load_store_creds,
)
from sap_fiori_crawler.constants import CREDS_ENV_VAR


def test_store_creds_default_client() -> None:
    creds = StoreCreds(user="CA8DKG", password="hdl001")
    assert creds.client == DEFAULT_CLIENT == "800"


def test_store_creds_custom_client() -> None:
    creds = StoreCreds(user="CA8DKG", password="hdl001", client="900")
    assert creds.client == "900"


def test_store_creds_is_frozen() -> None:
    creds = StoreCreds(user="CA8DKG", password="hdl001")
    with pytest.raises(Exception):  # FrozenInstanceError subclass differs by version
        creds.user = "X"  # type: ignore[misc]


def test_load_store_creds_happy() -> None:
    env = {CREDS_ENV_VAR: json.dumps({"CA8DKG": "hdl001", "CA9DKG": "hdl002"})}
    creds = load_store_creds("CA8DKG", env=env)
    assert creds.user == "CA8DKG"
    assert creds.password == "hdl001"
    assert creds.client == "800"


def test_load_store_creds_missing_env() -> None:
    with pytest.raises(FioriLoginError, match="env var is not set"):
        load_store_creds("CA8DKG", env={})


def test_load_store_creds_invalid_json() -> None:
    env = {CREDS_ENV_VAR: "not-json"}
    with pytest.raises(FioriLoginError, match="not valid JSON"):
        load_store_creds("CA8DKG", env=env)


def test_load_store_creds_not_an_object() -> None:
    env = {CREDS_ENV_VAR: json.dumps(["CA8DKG"])}
    with pytest.raises(FioriLoginError, match="must be a JSON object"):
        load_store_creds("CA8DKG", env=env)


def test_load_store_creds_unknown_store() -> None:
    env = {CREDS_ENV_VAR: json.dumps({"CA8DKG": "hdl001"})}
    with pytest.raises(FioriLoginError, match="No password for store"):
        load_store_creds("CA9DKG", env=env)


def test_load_store_creds_empty_password() -> None:
    env = {CREDS_ENV_VAR: json.dumps({"CA8DKG": ""})}
    with pytest.raises(FioriLoginError, match="No password for store"):
        load_store_creds("CA8DKG", env=env)


def test_load_store_creds_numeric_password() -> None:
    """Some passwords might be numeric in the JSON; coerce to string."""
    env = {CREDS_ENV_VAR: json.dumps({"CA8DKG": 12345})}
    creds = load_store_creds("CA8DKG", env=env)
    assert creds.password == "12345"

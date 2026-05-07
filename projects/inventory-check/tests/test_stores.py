"""Unit tests for inventory_check.stores."""
from __future__ import annotations

import pytest

from inventory_check.stores import all_stores, get_store


def test_get_store_known() -> None:
    s = get_store("CA8DKG")
    assert s.werks == "CA08"
    assert s.pos_name == "加拿大八店"


def test_get_store_unknown() -> None:
    with pytest.raises(KeyError, match="unknown store"):
        get_store("NONEXIST")


def test_all_stores_non_empty() -> None:
    stores = all_stores()
    assert len(stores) >= 1


def test_store_keys_are_unique() -> None:
    stores = all_stores()
    keys = [s.sap_user for s in stores]
    assert len(keys) == len(set(keys)), "duplicate sap_user in stores registry"


def test_store_werks_are_unique() -> None:
    stores = all_stores()
    werks = [s.werks for s in stores]
    assert len(werks) == len(set(werks)), "duplicate werks in stores registry"

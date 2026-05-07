"""Store registry — keyed by SAP user code (== Fiori login).

Initial entries cover the SGP Fiori demo creds the user provided.
``pos_name`` is the Chinese name shown in the POS portal store dropdown.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Store:
    sap_user: str  # also the Fiori user, e.g. "CA8DKG"
    werks: str  # SAP plant code, e.g. "CA08"
    pos_name: str  # POS portal display name, e.g. "加拿大八店"


_STORES: tuple[Store, ...] = (
    Store(sap_user="CA1DKG", werks="CA01", pos_name="加拿大一店"),
    Store(sap_user="CA2DKG", werks="CA02", pos_name="加拿大二店"),
    Store(sap_user="ca3dkg", werks="CA03", pos_name="加拿大三店"),
    Store(sap_user="CA4DKG", werks="CA04", pos_name="加拿大四店"),
    Store(sap_user="CA5DKG", werks="CA05", pos_name="加拿大五店"),
    Store(sap_user="CA6DKG", werks="CA06", pos_name="加拿大六店"),
    Store(sap_user="CA7DKG", werks="CA07", pos_name="加拿大七店"),
    Store(sap_user="CA8DKG", werks="CA08", pos_name="加拿大八店"),
)


def all_stores() -> tuple[Store, ...]:
    return _STORES


def get_store(sap_user: str) -> Store:
    for s in _STORES:
        if s.sap_user == sap_user:
            return s
    raise KeyError(f"unknown store {sap_user!r} — add to inventory_check.stores")

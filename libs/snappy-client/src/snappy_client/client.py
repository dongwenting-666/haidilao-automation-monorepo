"""Snappy POS API client for retrieving daily sales data."""

from __future__ import annotations

import base64
import logging
from datetime import date, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class SnappyClient:
    """Client for the Snappy POS Cloud API (gosnappy.io).

    Usage::

        with SnappyClient(username="express", password="90051232", store_id="90051") as client:
            client.login()
            sales = client.get_daily_sales(date(2026, 4, 3))
            # sales = {"net_sales": 1234.56, "order_count": 42}
    """

    def __init__(
        self,
        username: str,
        password: str,
        store_id: str,
        base_url: str = "https://gosnappy.io",
    ) -> None:
        self.username = username
        self.password = password
        self.store_id = store_id
        self.base_url = base_url.rstrip("/")
        self._token: str | None = None
        self._http: httpx.Client | None = None

    def __enter__(self) -> SnappyClient:
        self._http = httpx.Client(timeout=30.0)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._http:
            self._http.close()
            self._http = None

    def _ensure_http(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=30.0)
        return self._http

    def login(self) -> None:
        """Authenticate with the Snappy API and store the session token.

        POST /v1/bc/login/ with Basic auth header.
        """
        http = self._ensure_http()
        credentials = base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode()

        resp = http.post(
            f"{self.base_url}/v1/bc/login/",
            headers={
                "Authorization": f"Basic {credentials}",
                "storeid": self.store_id,
                "app-name": "BC",
                "environment": "NA",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        # Token comes in the response header, not the JSON body
        self._token = resp.headers.get("authorization", "")
        if not self._token:
            # Fallback: try JSON body
            data = resp.json()
            self._token = data.get("token") or data.get("access_token") or ""
        if not self._token:
            raise ValueError("No token found in login response headers or body")
        logger.info("Snappy login successful for store %s", self.store_id)

    def _auth_headers(self) -> dict[str, str]:
        if not self._token:
            raise RuntimeError("Not logged in — call login() first")
        return {
            "Authorization": self._token,
            "storeid": self.store_id,
            "app-name": "BC",
            "environment": "NA",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _date_to_utc_range(d: date) -> tuple[str, str]:
        """Convert a Vancouver-local date to UTC start/end timestamps.

        Vancouver is UTC-7 (PDT) / UTC-8 (PST). The API uses a fixed
        cutOffTimeInMinutes=480 (8 hours), so midnight Vancouver = 07:00 UTC.

        Returns (start_iso, end_iso) e.g.:
            ("2026-04-13T07:00:00.000Z", "2026-04-14T06:59:59.999Z")
        """
        # start: date at 07:00 UTC (midnight Vancouver in UTC-7)
        start = f"{d.isoformat()}T07:00:00.000Z"
        # end: next day at 06:59:59.999 UTC
        next_day = d + timedelta(days=1)
        end = f"{next_day.isoformat()}T06:59:59.999Z"
        return start, end

    def _fetch_sales(self, start_date: date, end_date: date) -> dict[str, Any]:
        """Fetch sales report for a date range.

        The range is inclusive: startDate = start_date midnight Vancouver,
        endDate = (end_date + 1 day) 06:59:59.999 UTC.
        """
        http = self._ensure_http()
        start_iso = f"{start_date.isoformat()}T00:00:00.000Z"
        end_iso = f"{end_date.isoformat()}T00:00:00.000Z"

        payload = {
            "periodGroupBy": "DAYS",
            "timeZone": "America/Vancouver",
            "queryDateType": "FINALIZED_DATE",
            "useStoreSalesV3API": True,
            "cutOffTimeInMinutes": 480,
            "environment": "NA",
            "periodFilter": {
                "startDate": start_iso,
                "endDate": end_iso,
            },
        }
        resp = http.post(
            "https://pos.gosnappy.io/api/pos_cloud/v1/report/sales/v2/stores",
            headers=self._auth_headers(),
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    def get_daily_sales(self, d: date) -> dict[str, Any]:
        """Get sales data for a single day.

        Returns {"net_sales": float (dollars), "order_count": int}.
        Values from the API are in cents — this method converts to dollars.
        """
        data = self._fetch_sales(d, d)
        return self._extract_sales(data)

    def get_mtd_sales(self, year: int, month: int, up_to_date: date) -> dict[str, Any]:
        """Get month-to-date sales from the 1st of the month to *up_to_date*.

        Returns {"net_sales": float (dollars), "order_count": int}.
        """
        start = date(year, month, 1)
        data = self._fetch_sales(start, up_to_date)
        return self._extract_sales(data)

    @staticmethod
    def _extract_sales(data: dict[str, Any]) -> dict[str, Any]:
        """Extract net_sales (dollars) and order_count from the API response."""
        sub_total_cents = 0
        order_count = 0

        rows = data.get("rows") or data.get("data", {}).get("rows") or []
        for row_wrapper in rows:
            row = row_wrapper.get("row", row_wrapper)
            summary = row.get("salesSummary", {})
            sub_total_cents += summary.get("netSales", 0) or summary.get("subTotal", 0)
            order_count += summary.get("orderQty", 0) or summary.get("transactionCount", 0)

        return {
            "net_sales": sub_total_cents / 100.0,
            "order_count": order_count,
        }

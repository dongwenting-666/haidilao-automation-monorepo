"""E2E test: full MB5B stock-report flow (connect → login → export → disconnect).

Requires:
    - SAP GUI running and connected to a system
    - Environment variables: SAP_USERNAME, SAP_PASSWORD
    - Optional: SAP_LANGUAGE (default: ZH)

Usage:
    uv run --project libs/sap-gui python libs/sap-gui/tests/e2e_mb5b.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from sap_gui.processes.mb5b import (
    DEFAULT_COMPANY_HIGH,
    DEFAULT_COMPANY_LOW,
    default_filename,
    previous_month_range,
    run,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output" / "mb5b"


def main() -> None:
    load_dotenv()

    username = os.environ.get("SAP_USERNAME", "")
    password = os.environ.get("SAP_PASSWORD", "")
    language = os.environ.get("SAP_LANGUAGE", "ZH")

    if not username or not password:
        print("ERROR: Set SAP_USERNAME and SAP_PASSWORD environment variables")
        sys.exit(1)

    d_from, d_to = previous_month_range()
    output_path = OUTPUT_DIR / default_filename(d_from)

    log.info("Starting MB5B E2E test")
    log.info("  User:     %s", username)
    log.info("  Companies: %s - %s", DEFAULT_COMPANY_LOW, DEFAULT_COMPANY_HIGH)
    log.info("  Dates:    %s – %s", d_from, d_to)
    log.info("  Output:   %s", output_path)

    t0 = time.monotonic()

    result = run(
        username=username,
        password=password,
        output_path=output_path,
        company_low=DEFAULT_COMPANY_LOW,
        company_high=DEFAULT_COMPANY_HIGH,
        date_from=d_from,
        date_to=d_to,
        language=language,
    )

    elapsed = time.monotonic() - t0
    if not result.exists():
        log.error("E2E FAILED — file not created at %s", result)
        sys.exit(1)

    size = result.stat().st_size
    if size == 0:
        log.error("E2E FAILED — file is empty: %s", result)
        sys.exit(1)

    log.info("=" * 60)
    log.info("E2E PASSED  %.1fs  %d bytes  %s", elapsed, size, result)


if __name__ == "__main__":
    main()

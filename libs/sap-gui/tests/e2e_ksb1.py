"""E2E test: full KSB1 export flow (connect → login → download → disconnect).

Requires:
    - SAP GUI running and connected to a system
    - Environment variables: SAP_USERNAME, SAP_PASSWORD
    - Optional: SAP_LANGUAGE (default: ZH)

Usage:
    uv run --project libs/sap-gui python libs/sap-gui/tests/e2e_ksb1.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from sap_gui.processes.ksb1 import run, DEFAULT_COST_CENTERS_FILE, previous_month_range

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger(__name__)

OUTPUT_DIR = (
    Path(__file__).resolve().parents[3] / "output" / "ksb1"
)


def main() -> None:
    load_dotenv()

    username = os.environ.get("SAP_USERNAME", "")
    password = os.environ.get("SAP_PASSWORD", "")
    language = os.environ.get("SAP_LANGUAGE", "ZH")

    if not username or not password:
        print("ERROR: Set SAP_USERNAME and SAP_PASSWORD environment variables")
        sys.exit(1)

    output_path = OUTPUT_DIR / "e2e_test.XLSX"
    d_from, d_to = previous_month_range()

    log.info("Starting KSB1 E2E test")
    log.info("  User:    %s", username)
    log.info("  Dates:   %s – %s", d_from, d_to)
    log.info("  Output:  %s", output_path)

    t0 = time.monotonic()

    result = run(
        username=username,
        password=password,
        cost_center_file=DEFAULT_COST_CENTERS_FILE,
        output_path=output_path,
        date_from=d_from,
        date_to=d_to,
        language=language,
    )

    elapsed = time.monotonic() - t0
    size = result.stat().st_size

    log.info("=" * 60)
    log.info("E2E PASSED  %.1fs  %d bytes  %s", elapsed, size, result)


if __name__ == "__main__":
    main()

"""Standalone VPN reconnect script (loop mode for Task Scheduler).

For use as middleware in automations, use ``from vpn import ensure_vpn`` instead.

Usage:
    python scripts/vpn_reconnect.py              # Run once
    python scripts/vpn_reconnect.py --loop        # Run continuously (default: every 7h)
    python scripts/vpn_reconnect.py --loop --interval 6
"""

import argparse
import logging
import sys
import time
from pathlib import Path

from vpn import ensure_vpn, VPNError

DEFAULT_INTERVAL_HOURS = 7
RETRY_INTERVAL_SECONDS = 300

LOG_DIR = Path(__file__).parent / "logs"
log = logging.getLogger(__name__)


def _setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_DIR / "vpn_reconnect.log", encoding="utf-8"),
        ],
    )


def main():
    parser = argparse.ArgumentParser(description="Auto-reconnect SealSuite VPN")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_HOURS,
        help=f"Hours between checks (default: {DEFAULT_INTERVAL_HOURS})",
    )
    parser.add_argument(
        "--max-hours",
        type=float,
        default=6.0,
        help="Cycle VPN if connected longer than this (default: 6.0)",
    )
    args = parser.parse_args()

    _setup_logging()

    if args.loop:
        log.info("Starting VPN reconnect loop (every %.1f hours)", args.interval)
        while True:
            try:
                ensure_vpn(max_connected_hours=args.max_hours)
                sleep_seconds = args.interval * 3600
                log.info("Sleeping for %.1f hours...", args.interval)
            except VPNError:
                sleep_seconds = RETRY_INTERVAL_SECONDS
                log.exception("Reconnect failed, retrying in %d seconds...", sleep_seconds)
            time.sleep(sleep_seconds)
    else:
        try:
            ensure_vpn(max_connected_hours=args.max_hours)
        except VPNError:
            log.exception("VPN ensure failed")
            sys.exit(1)


if __name__ == "__main__":
    main()

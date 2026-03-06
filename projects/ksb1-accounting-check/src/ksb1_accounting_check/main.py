"""KSB1 Accounting Check - main entry point."""

import os

from dotenv import load_dotenv

REQUIRED_ENV_VARS = ["SAP_USERNAME", "SAP_PASSWORD", "SAP_HOST"]


def main():
    """Run the KSB1 accounting check."""
    load_dotenv()

    missing = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing:
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")

    print("KSB1 Accounting Check - TODO: implement")


if __name__ == "__main__":
    main()

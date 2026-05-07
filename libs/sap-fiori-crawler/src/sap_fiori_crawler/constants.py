"""Shared constants for the SAP Fiori crawler."""
from __future__ import annotations

BASE_URL = "https://sgpfioriweb.superhi-tech.com"
LAUNCHPAD_URL = f"{BASE_URL}/sap/bc/ui2/flp#Shell-home"

DEFAULT_CLIENT = "800"

# Per-store credentials are stored as a JSON dict in this env var:
#   { "CA8DKG": "hdl001", "CA9DKG": "hdl001", ... }
CREDS_ENV_VAR = "SGPFIORIWEB_CREDS"

# Login flow is flaky; the user reports it usually takes 2–3 retries.
LOGIN_MAX_ATTEMPTS = 5

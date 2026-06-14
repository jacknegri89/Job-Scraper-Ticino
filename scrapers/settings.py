# Centralized scraper configuration.
# All values can be overridden by environment variable:
#   SCRAPER_HEADLESS=1       -> hidden browser
#   SCRAPER_TIMEOUT_MS=45000 -> navigation timeout in ms
#   SCRAPER_ATTEMPTS=3       -> scraper attempts (max 3)

import os
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, ""))
    except ValueError:
        return default


HEADLESS        = _env_bool("SCRAPER_HEADLESS", False)
PAGE_TIMEOUT_MS = _env_int("SCRAPER_TIMEOUT_MS", 30_000)
MAX_ATTEMPTS    = max(1, min(_env_int("SCRAPER_ATTEMPTS", 2), 3))
RETRY_BACKOFF_S = (3, 6)   # Waits: 3s after first failure, 6s after second.

DEBUG_DIR   = Path(__file__).parent.parent / "debug"
AUTH_DIR    = Path(__file__).parent.parent / "profile"
REPORT_FILE = Path(__file__).parent.parent / "scan_report.json"

# Configurazione centralizzata degli scraper.
# Tutti i valori sono sovrascrivibili da variabile d'ambiente:
#   SCRAPER_HEADLESS=1       → browser nascosto
#   SCRAPER_TIMEOUT_MS=45000 → timeout navigazione in ms
#   SCRAPER_ATTEMPTS=3       → tentativi per scraper (max 3)

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
RETRY_BACKOFF_S = (3, 6)   # secondi di attesa: 3s dopo il 1° fallimento, 6s dopo il 2°

DEBUG_DIR   = Path(__file__).parent.parent / "debug"
AUTH_DIR    = Path(__file__).parent.parent / "profile"
REPORT_FILE = Path(__file__).parent.parent / "scan_report.json"

"""
Configurazione centralizzata degli scraper.

Tutte le impostazioni sono sovrascrivibili da variabile d'ambiente,
così lo stesso codice gira in locale (headful, debug) e schedulato
(headless, silenzioso) senza modifiche.
"""

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


# Browser visibile di default (anti-bot più permissivo); SCRAPER_HEADLESS=1 per nasconderlo
HEADLESS = _env_bool("SCRAPER_HEADLESS", False)

# Timeout di navigazione predefinito per pagina (ms)
PAGE_TIMEOUT_MS = _env_int("SCRAPER_TIMEOUT_MS", 30_000)

# Tentativi totali per scraper (1 = nessun retry). Max consigliato 3.
MAX_ATTEMPTS = max(1, min(_env_int("SCRAPER_ATTEMPTS", 2), 3))

# Backoff breve fra tentativi (secondi): 3s dopo il 1° fallimento, 6s dopo il 2°
RETRY_BACKOFF_S = (3, 6)

# Cartella per artefatti di debug (screenshot + HTML dei fallimenti)
DEBUG_DIR = Path(__file__).parent.parent / "debug"

# Cartella per gli storage state delle sessioni autenticate manualmente
AUTH_DIR = Path(__file__).parent.parent / "profile"

# Report di fine scansione
REPORT_FILE = Path(__file__).parent.parent / "scan_report.json"

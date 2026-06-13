# Sessioni autenticate — MAI login automatici.
#
# Flusso:
#   1. python scraper.py --auth linkedin
#   2. si apre un browser visibile sulla pagina di login
#   3. l'utente fa login A MANO (funziona anche con 2FA)
#   4. lo script rileva il login riuscito e salva lo storage state in profile/
#   5. gli scraper riusano quella sessione nei run successivi
#
# Se la sessione manca o è scaduta, lo scraper segnala
# "requires_manual_login" senza fallire e senza tentare aggiramenti.

from __future__ import annotations

import time
from pathlib import Path

from scrapers.settings import AUTH_DIR

# Configurazione per sito autenticabile.
AUTH_SITES: dict[str, dict] = {
    "linkedin": {
        "login_url":      "https://www.linkedin.com/login",
        "success_urls":   ("/feed", "linkedin.com/in/"),
        "success_cookie": "li_at",
        "state_file":     "state_linkedin.json",
    },
    "indeed": {
        "login_url":      "https://secure.indeed.com/auth",
        "success_urls":   ("ch.indeed.com", "myaccount.indeed.com"),
        "success_cookie": "PPID",
        "state_file":     "state_indeed.json",
    },
}

WAIT_LOGIN_S = 300   # massimo 5 minuti per il login manuale


def auth_state_path(site: str) -> Path:
    cfg = AUTH_SITES.get(site)
    if not cfg:
        raise KeyError(f"Sito auth sconosciuto: {site!r}. Disponibili: {list(AUTH_SITES)}")
    return AUTH_DIR / cfg["state_file"]


def has_auth_state(site: str) -> bool:
    try:
        return auth_state_path(site).exists()
    except KeyError:
        return False


def _is_logged_in(context, cfg: dict) -> bool:
    # Login confermato dal cookie di sessione o dall'URL della pagina corrente.
    try:
        cookies = context.cookies()
        if any(c.get("name") == cfg["success_cookie"] and c.get("value") for c in cookies):
            return True
    except Exception:
        pass
    try:
        for pg in context.pages:
            url = (pg.url or "").lower()
            if any(s in url for s in cfg["success_urls"]):
                return True
    except Exception:
        pass
    return False


def run_auth_flow(playwright, site: str) -> bool:
    # Apre un browser visibile per il login manuale e salva lo storage state.
    # Ritorna True se la sessione è stata salvata con successo.
    cfg = AUTH_SITES.get(site)
    if not cfg:
        print(f"[AUTH] Sito sconosciuto: {site!r}. Disponibili: {', '.join(AUTH_SITES)}")
        return False

    AUTH_DIR.mkdir(exist_ok=True)
    state_path = auth_state_path(site)

    print(f"[AUTH] Apro {cfg['login_url']}")
    print(f"[AUTH] Fai login manualmente nella finestra del browser.")
    print(f"[AUTH] Hai {WAIT_LOGIN_S // 60} minuti; la sessione si salva da sola appena entri.")

    browser = playwright.chromium.launch(headless=False,
                                         args=["--disable-blink-features=AutomationControlled"])
    context = browser.new_context(locale="it-CH", timezone_id="Europe/Zurich")
    page = context.new_page()
    try:
        page.goto(cfg["login_url"], wait_until="domcontentloaded", timeout=60_000)

        deadline = time.monotonic() + WAIT_LOGIN_S
        while time.monotonic() < deadline:
            if _is_logged_in(context, cfg):
                context.storage_state(path=str(state_path))
                print(f"[AUTH] Login rilevato — sessione salvata in {state_path}")
                return True
            time.sleep(2)
            if not context.pages:
                break   # l'utente ha chiuso il browser manualmente

        print("[AUTH] Login non rilevato entro il tempo massimo. Sessione NON salvata.")
        return False
    finally:
        try:
            browser.close()
        except Exception:
            pass

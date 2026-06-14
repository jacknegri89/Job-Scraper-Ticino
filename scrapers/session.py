# Authenticated sessions: NEVER automatic logins.
#
# Flow:
#   1. python scraper.py --auth linkedin
#   2. a visible browser opens on the login page
#   3. the user logs in MANUALLY, including any 2FA
#   4. the script detects a successful login and saves storage state in profile/
#   5. scrapers reuse that session in later runs
#
# If the session is missing or expired, the scraper reports
# "requires_manual_login" without failing and without bypass attempts.

from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import BrowserContext, Playwright

from scrapers.settings import AUTH_DIR

# Configuration for sites that can use a manual authenticated session.
AUTH_SITES: dict[str, dict[str, str | tuple[str, ...]]] = {
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

WAIT_LOGIN_S = 300   # Up to 5 minutes for manual login.


def auth_state_path(site: str) -> Path:
    cfg = AUTH_SITES.get(site)
    if not cfg:
        raise KeyError(f"Unknown auth site: {site!r}. Available: {list(AUTH_SITES)}")
    return AUTH_DIR / cfg["state_file"]


def has_auth_state(site: str) -> bool:
    try:
        return auth_state_path(site).exists()
    except KeyError:
        return False


def _is_logged_in(context: BrowserContext, cfg: dict[str, str | tuple[str, ...]]) -> bool:
    # Login is confirmed by the session cookie or the current page URL.
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


def run_auth_flow(playwright: Playwright, site: str) -> bool:
    # Open a visible browser for manual login and save storage state.
    # Return True when the session was saved successfully.
    cfg = AUTH_SITES.get(site)
    if not cfg:
        print(f"[AUTH] Unknown site: {site!r}. Available: {', '.join(AUTH_SITES)}")
        return False

    AUTH_DIR.mkdir(exist_ok=True)
    state_path = auth_state_path(site)

    print(f"[AUTH] Opening {cfg['login_url']}")
    print("[AUTH] Log in manually in the browser window.")
    print(f"[AUTH] You have {WAIT_LOGIN_S // 60} minutes; the session saves after login.")

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
                print(f"[AUTH] Login detected - session saved in {state_path}")
                return True
            time.sleep(2)
            if not context.pages:
                break   # The user manually closed the browser.

        print("[AUTH] Login was not detected before timeout. Session NOT saved.")
        return False
    finally:
        try:
            browser.close()
        except Exception:
            pass

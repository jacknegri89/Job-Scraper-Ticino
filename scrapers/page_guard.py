# Page gate detection: cookie banners, required login, captcha/block pages.
#
# - Cookie banners are closed with domain rules plus generic fallbacks.
# - Login and captcha pages are never bypassed; they are detected and reported
#   to the caller as "requires_auth" or "blocked".

from __future__ import annotations

from playwright.sync_api import Page

# CSS selectors for cookie banners, configured by domain.
# Key = page-domain substring. Order favors reject buttons before accept buttons.
COOKIE_RULES: dict[str, list[str]] = {
    "jobs.ch": [
        'button#onetrust-reject-all-handler',
        'button#onetrust-accept-btn-handler',
    ],
    "jobscout24.ch": [
        # JobScout24 only offers "Akzeptieren"; there is no reject button.
        'button:text("Akzeptieren")',
        'button:has-text("Akzeptieren")',
        'button[class*="cookie"][class*="accept"]',
        'button[id*="cookie"]',
    ],
    "indeed.com": [
        'button#onetrust-reject-all-handler',
        'button[id*="onetrust-accept"]',
        'button:has-text("Rifiuta tutti")',
        'button:has-text("Accetta tutti")',
    ],
    "randstad.ch": [
        'button#onetrust-reject-all-handler',
        'button:has-text("rifiuta tutti")',
        'button:has-text("Rifiuta tutti")',
    ],
    "adecco.com": [
        'button#onetrust-reject-all-handler',
        'button#onetrust-accept-btn-handler',
    ],
    "manpower.ch": [
        'button#onetrust-reject-all-handler',
        'button#onetrust-accept-btn-handler',
    ],
    "orienta.ch": [
        'button:has-text("Rifiuta")',
        'button:has-text("Accetta")',
    ],
    "gigroup.com": [
        'button#onetrust-reject-all-handler',
        'button:has-text("Rifiuta")',
        'button#onetrust-accept-btn-handler',
    ],
    "linkedin.com": [
        'button[action-type="DENY"]',
        'button:has-text("Rifiuta")',
        'button:has-text("Reject")',
    ],
}

# Generic selectors tried on any domain without a dedicated rule.
# Buttons only: links or other elements can trigger unwanted navigation.
GENERIC_COOKIE_SELECTORS = [
    'button#onetrust-reject-all-handler',
    'button:has-text("Essential cookies only")',
    'button:has-text("Nega il consenso")',
    'button:has-text("Reject all")',
    'button:has-text("Rifiuta tutto")',
    'button:has-text("Rifiuta tutti")',
    'button:has-text("rifiuta tutti")',
    'button:has-text("Rifiuta")',
    'button:has-text("Akzeptieren")',
    'button#onetrust-accept-btn-handler',
    'button:has-text("Accetta tutti")',
]


def _domain_of(page: Page) -> str:
    try:
        from urllib.parse import urlparse
        return (urlparse(page.url).hostname or "").lower()
    except Exception:
        return ""


def _cookie_rules_for(domain: str) -> list[str]:
    for key, selectors in COOKIE_RULES.items():
        if key in domain:
            return selectors
    return []


def _cookie_candidates(domain: str) -> list[str]:
    rules = _cookie_rules_for(domain)
    fallbacks = [selector for selector in GENERIC_COOKIE_SELECTORS if selector not in rules]
    return rules + fallbacks


def _click_cookie_button(page: Page, selector: str) -> bool:
    try:
        button = page.query_selector(selector)
        if not button or not button.is_visible():
            return False
        button.click()
        page.wait_for_timeout(1200)
        return True
    except Exception:
        return False


def _remove_onetrust_overlay(page: Page) -> bool:
    try:
        removed = page.evaluate(
            "() => { const els = document.querySelectorAll("
            "'#onetrust-consent-sdk, .onetrust-pc-dark-filter');"
            "els.forEach(e => e.remove()); return els.length; }"
        )
        return bool(removed)
    except Exception:
        return False


def dismiss_cookies(page: Page, site: str = "") -> str | None:
    # Close the visible cookie banner and return the clicked selector, if any.
    domain = _domain_of(page)
    clicked = _first_clicked_cookie_selector(page, _cookie_candidates(domain))
    if clicked:
        print(f"  [cookie] {site or domain}: clicked {clicked}")
    if _remove_onetrust_overlay(page) and not clicked:
        print(f"  [cookie] {site or domain}: OneTrust overlay removed from DOM")
    return clicked


def _first_clicked_cookie_selector(page: Page, selectors: list[str]) -> str | None:
    for selector in selectors:
        if _click_cookie_button(page, selector):
            return selector
    return None


# URL patterns that indicate a login page.
AUTH_URL_PATTERNS = (
    "/login", "/signin", "/sign-in", "/auth/", "authwall",
    "/account/login", "checkpoint/lg", "/registrazione", "/register",
    "secure.indeed.com", "/uas/login",
)

# Page-title patterns that indicate an auth gate.
AUTH_TITLE_PATTERNS = (
    "accedi", "sign in", "log in", "login", "anmelden",
    "join linkedin", "registrati", "create account", "account indeed",
)


def detect_auth_gate(page: Page) -> str | None:
    # Return a reason when the page is a login gate, otherwise None.
    # Conservative: a navbar "Accedi" link alone must not trigger detection.
    try:
        return _auth_gate_reason(page)
    except Exception:
        return None


def _auth_gate_reason(page: Page) -> str | None:
    return (
        _login_url_reason(page)
        or _login_title_reason(page)
        or _password_form_reason(page)
    )


def _login_url_reason(page: Page) -> str | None:
    url = (page.url or "").lower()
    for pattern in AUTH_URL_PATTERNS:
        if pattern in url:
            return f"login URL ({pattern})"
    return None


def _login_title_reason(page: Page) -> str | None:
    title = (page.title() or "").lower()
    for pattern in AUTH_TITLE_PATTERNS:
        if pattern in title:
            return f"login title ({title[:60]!r})"
    return None


def _password_form_reason(page: Page) -> str | None:
    password_input = page.query_selector('input[type="password"]')
    if password_input and password_input.is_visible():
        return "visible password form"
    return None


# Signals that indicate an anti-bot or captcha block.
BLOCK_SIGNALS = (
    "captcha", "unusual traffic", "access denied", "403 forbidden",
    "please verify", "verifica di essere", "non sono un robot",
    "are you a robot", "cloudflare", "attention required",
    "rate limit", "too many requests",
)


def detect_block(page: Page) -> str | None:
    try:
        title = (page.title() or "").lower()
        url   = (page.url or "").lower()
        for s in BLOCK_SIGNALS:
            if s in title or s in url:
                return f"anti-bot signal ({s})"
    except Exception:
        pass
    return None

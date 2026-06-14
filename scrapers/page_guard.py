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


def dismiss_cookies(page: Page, site: str = "") -> str | None:
    # Close the visible cookie banner and return the clicked selector, if any.
    domain = _domain_of(page)
    rules: list[str] = []
    for key, sels in COOKIE_RULES.items():
        if key in domain:
            rules = sels
            break
    candidates = rules + [s for s in GENERIC_COOKIE_SELECTORS if s not in rules]

    clicked = None
    for sel in candidates:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(1200)
                clicked = sel
                print(f"  [cookie] {site or domain}: clicked {sel}")
                break
        except Exception:
            continue

    # OneTrust sometimes leaves an overlay after the click; remove it so it
    # cannot intercept later clicks.
    try:
        removed = page.evaluate(
            "() => { const els = document.querySelectorAll("
            "'#onetrust-consent-sdk, .onetrust-pc-dark-filter');"
            "els.forEach(e => e.remove()); return els.length; }"
        )
        if removed and not clicked:
            print(f"  [cookie] {site or domain}: OneTrust overlay removed from DOM")
    except Exception:
        pass

    return clicked


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
        url = (page.url or "").lower()
        for pat in AUTH_URL_PATTERNS:
            if pat in url:
                return f"login URL ({pat})"

        title = (page.title() or "").lower()
        for pat in AUTH_TITLE_PATTERNS:
            if pat in title:
                return f"login title ({title[:60]!r})"

        pwd = page.query_selector('input[type="password"]')
        if pwd and pwd.is_visible():
            return "visible password form"
    except Exception:
        pass
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

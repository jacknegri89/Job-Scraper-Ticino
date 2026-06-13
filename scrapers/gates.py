"""
Rilevamento "gate" delle pagine: cookie banner, login richiesto, captcha/blocco.

Filosofia:
- I cookie banner si chiudono con regole configurabili per dominio + fallback
  generico, loggando SEMPRE che cosa è stato cliccato.
- Login/captcha NON si aggirano mai: si rilevano e si riporta uno stato
  pulito (requires_auth / blocked) al chiamante.
"""

from __future__ import annotations


# ────────────────────────────────────────────────────────────────
# Cookie banner
# ────────────────────────────────────────────────────────────────

# Selettori PROVATI per dominio (in ordine di preferenza: prima il rifiuto).
# Chiave = sottostringa del dominio della pagina corrente.
COOKIE_RULES: dict[str, list[str]] = {
    "jobs.ch": [
        'button#onetrust-reject-all-handler',
        'button#onetrust-accept-btn-handler',
    ],
    "jobscout24.ch": [
        # JobScout24 offre solo "Akzeptieren" (nessun pulsante rifiuta)
        'button:text("Akzeptieren")',  # Playwright :text() instead of :has-text()
        'button:has-text("Akzeptieren")',  # fallback: :has-text() syntax
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

# Fallback generico, provato su qualsiasi dominio senza regola dedicata.
# Solo <button>: mai link o elementi generici (un click sbagliato può navigare).
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
    'button#onetrust-accept-btn-handler',   # ultimo fallback: accetta pur di sbloccare
    'button:has-text("Accetta tutti")',
]


def _domain_of(page) -> str:
    try:
        from urllib.parse import urlparse
        return (urlparse(page.url).hostname or "").lower()
    except Exception:
        return ""


def dismiss_cookies(page, site: str = "") -> str | None:
    """
    Chiude il banner cookie se visibile.
    Ritorna il selettore cliccato (per il log) o None se nessun banner.

    site: etichetta usata solo per il log (es. "jobs.ch").
    """
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
                print(f"  [cookie] {site or domain}: cliccato {sel}")
                break
        except Exception:
            continue

    # Rete di sicurezza: l'overlay OneTrust a volte resta nel DOM e
    # intercetta i click anche senza pulsanti visibili — rimuovilo.
    try:
        removed = page.evaluate(
            "() => { const els = document.querySelectorAll("
            "'#onetrust-consent-sdk, .onetrust-pc-dark-filter');"
            "els.forEach(e => e.remove()); return els.length; }"
        )
        if removed and not clicked:
            print(f"  [cookie] {site or domain}: overlay OneTrust rimosso dal DOM")
    except Exception:
        pass

    return clicked


# ────────────────────────────────────────────────────────────────
# Login / auth gate
# ────────────────────────────────────────────────────────────────

# Pattern URL inequivocabili di pagine di login
AUTH_URL_PATTERNS = (
    "/login", "/signin", "/sign-in", "/auth/", "authwall",
    "/account/login", "checkpoint/lg", "/registrazione", "/register",
    "secure.indeed.com", "/uas/login",
)

# Titoli di pagina che indicano un gate di autenticazione
AUTH_TITLE_PATTERNS = (
    "accedi", "sign in", "log in", "login", "anmelden",
    "join linkedin", "registrati", "create account", "account indeed",
)


def detect_auth_gate(page) -> str | None:
    """
    Ritorna una stringa-motivo se la pagina corrente è un gate di login,
    None altrimenti. Conservativo: il link "Accedi" nella navbar di un
    portale NON fa scattare il rilevamento; serve un segnale forte
    (URL di login, titolo di login, o form password visibile).
    """
    try:
        url = (page.url or "").lower()
        for pat in AUTH_URL_PATTERNS:
            if pat in url:
                return f"URL di login ({pat})"

        title = (page.title() or "").lower()
        for pat in AUTH_TITLE_PATTERNS:
            if pat in title:
                return f"titolo di login ({title[:60]!r})"

        # Form password visibile = gate quasi certo
        pwd = page.query_selector('input[type="password"]')
        if pwd and pwd.is_visible():
            return "form password visibile"
    except Exception:
        pass
    return None


# ────────────────────────────────────────────────────────────────
# Captcha / blocco anti-bot
# ────────────────────────────────────────────────────────────────

BLOCK_SIGNALS = (
    "captcha", "unusual traffic", "access denied", "403 forbidden",
    "please verify", "verifica di essere", "non sono un robot",
    "are you a robot", "cloudflare", "attention required",
    "rate limit", "too many requests",
)


def detect_block(page) -> str | None:
    """Ritorna una stringa-motivo se la pagina è un blocco anti-bot/captcha."""
    try:
        title = (page.title() or "").lower()
        url   = (page.url or "").lower()
        for s in BLOCK_SIGNALS:
            if s in title or s in url:
                return f"segnale anti-bot ({s})"
    except Exception:
        pass
    return None

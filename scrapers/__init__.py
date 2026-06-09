import random
import time
import functools
from pathlib import Path

from playwright.sync_api import Playwright, BrowserContext

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]

VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
]

PROFILE_DIR = Path(__file__).parent.parent / "profile"
SESSION_FILE = PROFILE_DIR / "state.json"


def create_browser_context(playwright: Playwright) -> tuple:
    """Launch Chrome with maximum anti-detection settings. Returns (browser, context)."""
    PROFILE_DIR.mkdir(exist_ok=True)

    ua       = random.choice(USER_AGENTS)
    viewport = random.choice(VIEWPORTS)

    browser = playwright.chromium.launch(
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            f"--window-size={viewport['width']},{viewport['height']}",
        ],
    )

    context_kwargs = {
        "user_agent": ua,
        "viewport": viewport,
        "locale": "it-CH",
        "timezone_id": "Europe/Zurich",
        "extra_http_headers": {"Accept-Language": "it-CH,it;q=0.9,en;q=0.8"},
    }
    if SESSION_FILE.exists():
        context_kwargs["storage_state"] = str(SESSION_FILE)

    context = browser.new_context(**context_kwargs)
    return browser, context


def new_stealth_page(context: BrowserContext):
    """Create a page with playwright-stealth patches applied."""
    from playwright_stealth import Stealth
    page = context.new_page()
    Stealth().apply_stealth_sync(page)
    return page


def human_delay(min_s: float = 3.0, max_s: float = 8.0):
    time.sleep(random.uniform(min_s, max_s))


def human_scroll(page):
    """Scroll gradually to simulate a human reading the page."""
    page.evaluate(
        "() => new Promise(resolve => {"
        "  let y = 0;"
        "  const step = () => {"
        "    y += Math.floor(Math.random() * 120) + 40;"
        "    window.scrollTo(0, y);"
        "    if (y < document.body.scrollHeight * 0.6) setTimeout(step, 120);"
        "    else resolve();"
        "  };"
        "  step();"
        "})"
    )


def dismiss_cookie_dialog(page):
    """Click the minimal/reject cookie button if a consent dialog is visible."""
    selectors = [
        'button:has-text("Essential cookies only")',
        'button:has-text("Nega il consenso")',
        'button:has-text("Reject all")',
        'button:has-text("Rifiuta tutto")',
    ]
    for sel in selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(1500)
                return
        except Exception:
            pass


def fetch_description(context: BrowserContext, url: str, max_chars: int = 1000) -> str:
    """
    Apre la pagina dell'annuncio e restituisce il testo della descrizione (max max_chars).
    Ritorna stringa vuota in caso di errore.
    """
    if not url or not url.startswith(("https://", "http://")):
        return ""
    try:
        page = new_stealth_page(context)
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        dismiss_cookie_dialog(page)
        page.wait_for_timeout(1500)

        # Prova selettori comuni per la descrizione
        selectors = [
            "[data-cy='job-description']",
            ".job-description",
            ".job-detail__description",
            ".jobdescription",
            "article",
            "main",
        ]
        testo = ""
        for sel in selectors:
            el = page.query_selector(sel)
            if el:
                testo = el.inner_text()
                if len(testo.strip()) > 100:
                    break

        # Fallback: testo del body pulito
        if len(testo.strip()) < 100:
            testo = page.evaluate("() => document.body.innerText")

        page.close()
        # Pulizia: rimuove righe vuote multiple e tronca
        lines = [l.strip() for l in testo.splitlines() if l.strip()]
        testo_pulito = " | ".join(lines)
        return testo_pulito[:max_chars]
    except Exception:
        return ""


def save_session(context: BrowserContext):
    """Persist cookies and storage state for the next run."""
    PROFILE_DIR.mkdir(exist_ok=True)
    try:
        context.storage_state(path=str(SESSION_FILE))
        print("[OK] Sessione salvata.")
    except Exception as e:
        print(f"[WARN] Impossibile salvare sessione: {e}")


def retry(max_attempts: int = 3):
    """Decorator: retry on exception with exponential backoff (10s, 20s, 40s)."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        print(f"[ERRORE] {func.__name__} fallito dopo {max_attempts} tentativi: {e}")
                        return []
                    delay = 10 * (2 ** attempt)
                    print(f"[RETRY] Tentativo {attempt + 1} fallito. Riprovo tra {delay}s…")
                    time.sleep(delay)
        return wrapper
    return decorator

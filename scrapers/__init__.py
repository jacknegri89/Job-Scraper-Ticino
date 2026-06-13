import re
import random
import time
import functools
from pathlib import Path

_EMAIL_RE    = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,10}\b')
# Indirizzi sistematici da ignorare: noreply, sistemi ATS, portali di job
_EMAIL_NOISE = (
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "postmaster", "mailer-daemon", "bounce", "notifications@",
    "indeed.com", "jobs.ch", "jobscout24", "randstad", "orienta",
    "gigroup", "carriera.ch", "monster.ch", "adecco.ch", "manpower.ch",
)


def extract_email(text: str) -> str:
    """Restituisce il primo indirizzo email utile nel testo (filtra sistemi automatici)."""
    for m in _EMAIL_RE.finditer(text):
        email = m.group().lower()
        if not any(noise in email for noise in _EMAIL_NOISE):
            return email
    return ""


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


def create_browser_context(playwright: Playwright, headless: bool = None) -> tuple:
    """Launch Chrome with maximum anti-detection settings. Returns (browser, context)."""
    from scrapers.settings import HEADLESS
    if headless is None:
        headless = HEADLESS
    PROFILE_DIR.mkdir(exist_ok=True)

    ua       = random.choice(USER_AGENTS)
    viewport = random.choice(VIEWPORTS)

    browser = playwright.chromium.launch(
        headless=headless,
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
    # Default per le chiamate senza timeout esplicito (i goto degli scraper
    # passano comunque il proprio timeout, che ha la precedenza)
    from scrapers.settings import PAGE_TIMEOUT_MS
    context.set_default_navigation_timeout(PAGE_TIMEOUT_MS)
    return browser, context


def new_stealth_page(context: BrowserContext):
    """Create a page with playwright-stealth patches applied."""
    from playwright_stealth import Stealth
    page = context.new_page()
    try:
        Stealth().apply_stealth_sync(page)
    except Exception:
        page.close()
        raise
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


def click_load_more(page, btn_texts, count_js, max_clicks=30, wait_ms=3000):
    """
    Clicca ripetutamente un pulsante "carica altri" finché:
    - nessun pulsante è visibile, oppure
    - il conteggio degli elementi DOM (count_js) non cresce per 2 cicli di fila.

    btn_texts : lista di testi da cercare nel pulsante (primo match vince)
    count_js  : snippet JS che ritorna il numero attuale di elementi nella pagina
                (usato per capire se il click ha caricato nuovi risultati)
    max_clicks: sicurezza anti-loop-infinito
    wait_ms   : millisecondi di attesa dopo ogni click

    Esempio uso:
        click_load_more(
            page,
            btn_texts=["Visualizza altri", "Mostra altri"],
            count_js="Array.from(document.querySelectorAll('a[href*=\"/it/lavoro/\"]'))"
                     ".filter(a=>/[a-f0-9]{8}/.test(a.getAttribute('href')||'')).length",
        )
    """
    prev_count = page.evaluate(count_js)
    no_change  = 0

    for click_n in range(1, max_clicks + 1):
        btn = None
        for text in btn_texts:
            try:
                b = page.query_selector(f'button:has-text("{text}")')
                if b and b.is_visible():
                    btn = b
                    break
            except Exception as e:
                print(f"    [load-more] query_selector('{text}') fallito: {e}")

        if btn is None:
            break   # Pulsante sparito → tutti i risultati visibili

        try:
            btn.click()
        except Exception as e:
            print(f"    [load-more] btn.click() fallito al click #{click_n}: {e}")
            break

        page.wait_for_timeout(wait_ms)
        human_scroll(page)
        page.wait_for_timeout(1000)

        new_count = page.evaluate(count_js)
        delta = new_count - prev_count
        print(f"    [load-more] click #{click_n}: {prev_count}→{new_count} ({delta:+d})")

        if new_count <= prev_count:
            no_change += 1
            if no_change >= 2:
                break   # 2 click senza nuovi elementi → fermati
        else:
            no_change = 0

        prev_count = new_count

    return prev_count


def dismiss_cookie_dialog(page, site: str = ""):
    """Chiude il banner cookie (regole per dominio + fallback). Vedi page_guard.py."""
    from scrapers.page_guard import dismiss_cookies
    return dismiss_cookies(page, site)


def fetch_description(context: BrowserContext, url: str, max_chars: int = 3000) -> dict:
    """
    Apre la pagina dell'annuncio.
    Ritorna {"description": str, "email": str}.
    L'email viene estratta dal testo completo PRIMA del troncamento.
    """
    empty = {"description": "", "email": ""}
    if not url or not url.startswith(("https://", "http://")):
        return empty
    page = None
    try:
        page = new_stealth_page(context)
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        dismiss_cookie_dialog(page)
        page.wait_for_timeout(1500)

        selectors = [
            "[data-cy='job-description']",
            "#jobDescriptionText",       # Indeed
            ".jobsearch-jobDescriptionText",  # Indeed alternativo
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

        if len(testo.strip()) < 100:
            testo = page.evaluate("() => document.body.innerText")

        lines = [l.strip() for l in testo.splitlines() if l.strip()]
        testo_pulito = " | ".join(lines)

        # Estrai email dal testo COMPLETO prima di troncare
        email = extract_email(testo_pulito)

        return {"description": testo_pulito[:max_chars], "email": email}
    except Exception as e:
        print(f"  [DESC] errore su {url[:60]}: {type(e).__name__}")
        return empty
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass


def save_session(context: BrowserContext):
    """Persist cookies and storage state for the next run."""
    PROFILE_DIR.mkdir(exist_ok=True)
    try:
        context.storage_state(path=str(SESSION_FILE))
        print("[OK] Sessione salvata.")
    except Exception as e:
        print(f"[WARN] Impossibile salvare sessione: {e}")


def retry(max_attempts: int = None):
    """
    Decorator per gli scraper: pochi tentativi, backoff breve.

    - max 2-3 tentativi (config.MAX_ATTEMPTS, sovrascrivibile per scraper)
    - backoff 3s / 6s fra i tentativi
    - errori irrecuperabili (browser chiuso, rete abortita) → nessun retry
    - dopo l'ultimo fallimento solleva ScrapeError con stato classificato:
      il runner la cattura, registra il sito nel report e prosegue.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            from scrapers.settings import MAX_ATTEMPTS, RETRY_BACKOFF_S
            from scrapers.site_report import classify_exception, ScrapeError
            attempts = min(max_attempts or MAX_ATTEMPTS, 3)

            for attempt in range(attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    status, reason = classify_exception(e)
                    # Irrecuperabile o ultimo tentativo → riporta al runner
                    if status in ("browser_closed", "network_error") or attempt == attempts - 1:
                        print(f"[ERRORE] {func.__name__}: {status} — {reason}")
                        raise ScrapeError(status, reason, attempt + 1) from e
                    delay = RETRY_BACKOFF_S[min(attempt, len(RETRY_BACKOFF_S) - 1)]
                    print(f"[RETRY] {func.__name__} tentativo {attempt + 1}/{attempts}"
                          f" fallito ({status}). Riprovo tra {delay}s…")
                    time.sleep(delay)
        return wrapper
    return decorator

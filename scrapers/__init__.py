import re
import random
import time
import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

from playwright.sync_api import Browser, BrowserContext, Page, Playwright

_EMAIL_RE    = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,10}\b')
# System addresses to ignore: noreply senders, ATS systems, and job portals.
_EMAIL_NOISE = (
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "postmaster", "mailer-daemon", "bounce", "notifications@",
    "indeed.com", "jobs.ch", "jobscout24", "randstad", "orienta",
    "gigroup", "carriera.ch", "monster.ch", "adecco.ch", "manpower.ch",
)

_P = ParamSpec("_P")
_R = TypeVar("_R")


def extract_email(text: str) -> str:
    """Return the first usable email address in text, excluding automated systems."""
    for m in _EMAIL_RE.finditer(text):
        email = m.group().lower()
        if not any(noise in email for noise in _EMAIL_NOISE):
            return email
    return ""


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


def create_browser_context(playwright: Playwright, headless: bool | None = None) -> tuple[Browser, BrowserContext]:
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

    context_kwargs: dict[str, Any] = {
        "user_agent": ua,
        "viewport": viewport,
        "locale": "it-CH",
        "timezone_id": "Europe/Zurich",
        "extra_http_headers": {"Accept-Language": "it-CH,it;q=0.9,en;q=0.8"},
    }
    if SESSION_FILE.exists():
        context_kwargs["storage_state"] = str(SESSION_FILE)

    context = browser.new_context(**context_kwargs)
    # Default for calls without an explicit timeout; scraper goto calls can
    # still pass their own timeout, which takes precedence.
    from scrapers.settings import PAGE_TIMEOUT_MS
    context.set_default_navigation_timeout(PAGE_TIMEOUT_MS)
    return browser, context


def new_stealth_page(context: BrowserContext) -> Page:
    """Create a page with playwright-stealth patches applied."""
    from playwright_stealth import Stealth
    page = context.new_page()
    try:
        Stealth().apply_stealth_sync(page)
    except Exception:
        page.close()
        raise
    return page


def human_delay(min_s: float = 3.0, max_s: float = 8.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def human_scroll(page: Page) -> None:
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


def click_load_more(
    page: Page,
    btn_texts: list[str],
    count_js: str,
    max_clicks: int = 30,
    wait_ms: int = 3000,
) -> int:
    """
    Repeatedly click a load-more button until:
    - no button is visible, or
    - the DOM element count (count_js) does not grow for 2 consecutive cycles.

    btn_texts : button labels to try; first visible match wins
    count_js  : JS snippet returning the current item count
    max_clicks: loop guard
    wait_ms   : milliseconds to wait after each click

    Example:
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
                print(f"    [load-more] query_selector('{text}') failed: {e}")

        if btn is None:
            break   # Button disappeared: all results are visible.

        try:
            btn.click()
        except Exception as e:
            print(f"    [load-more] btn.click() failed on click #{click_n}: {e}")
            break

        page.wait_for_timeout(wait_ms)
        human_scroll(page)
        page.wait_for_timeout(1000)

        new_count = page.evaluate(count_js)
        delta = new_count - prev_count
        print(f"    [load-more] click #{click_n}: {prev_count}->{new_count} ({delta:+d})")

        if new_count <= prev_count:
            no_change += 1
            if no_change >= 2:
                break   # Stop after 2 clicks without new items.
        else:
            no_change = 0

        prev_count = new_count

    return prev_count


def dismiss_cookie_dialog(page: Page, site: str = "") -> str | None:
    """Close the cookie banner using domain rules plus fallback selectors."""
    from scrapers.page_guard import dismiss_cookies
    return dismiss_cookies(page, site)


def fetch_description(context: BrowserContext, url: str, max_chars: int = 3000) -> dict[str, str]:
    """
    Open a job page and return {"description": str, "email": str}.
    Email extraction uses the full text before description truncation.
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
        description_text = ""
        for sel in selectors:
            el = page.query_selector(sel)
            if el:
                description_text = el.inner_text()
                if len(description_text.strip()) > 100:
                    break

        if len(description_text.strip()) < 100:
            description_text = page.evaluate("() => document.body.innerText")

        lines = [line.strip() for line in description_text.splitlines() if line.strip()]
        clean_text = " | ".join(lines)

        # Extract email from the full text before truncating the description.
        email = extract_email(clean_text)

        return {"description": clean_text[:max_chars], "email": email}
    except Exception as e:
        print(f"  [DESC] error on {url[:60]}: {type(e).__name__}")
        return empty
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass


def save_session(context: BrowserContext) -> None:
    """Persist cookies and storage state for the next run."""
    PROFILE_DIR.mkdir(exist_ok=True)
    try:
        context.storage_state(path=str(SESSION_FILE))
        print("[OK] Session saved.")
    except Exception as e:
        print(f"[WARN] Could not save session: {e}")


def retry(max_attempts: int | None = None) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """
    Decorator for scrapers: few attempts, short backoff.

    - max 2-3 attempts (settings.MAX_ATTEMPTS, overrideable per scraper)
    - 3s / 6s backoff between attempts
    - unrecoverable errors (closed browser, aborted network) are not retried
    - after the final failure, raises ScrapeError with a classified status
    """
    def decorator(func: Callable[_P, _R]) -> Callable[_P, _R]:
        @functools.wraps(func)
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            from scrapers.settings import MAX_ATTEMPTS, RETRY_BACKOFF_S
            from scrapers.site_report import classify_exception, ScrapeError
            attempts = min(max_attempts or MAX_ATTEMPTS, 3)

            for attempt in range(attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    status, reason = classify_exception(e)
                    # Bubble unrecoverable errors or the final attempt to the runner.
                    if status in ("browser_closed", "network_error") or attempt == attempts - 1:
                        print(f"[ERROR] {func.__name__}: {status} - {reason}")
                        raise ScrapeError(status, reason, attempt + 1) from e
                    delay = RETRY_BACKOFF_S[min(attempt, len(RETRY_BACKOFF_S) - 1)]
                    print(f"[RETRY] {func.__name__} attempt {attempt + 1}/{attempts}"
                          f" failed ({status}). Retrying in {delay}s...")
                    time.sleep(delay)
        return wrapper
    return decorator

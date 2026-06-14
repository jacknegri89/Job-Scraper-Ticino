import re
import random
import time
import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn, ParamSpec, TypeVar

from playwright.sync_api import Browser, BrowserContext, ElementHandle, Page, Playwright

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

    resolved_headless = HEADLESS if headless is None else headless
    PROFILE_DIR.mkdir(exist_ok=True)
    viewport = random.choice(VIEWPORTS)
    browser = _launch_browser(playwright, resolved_headless, viewport)
    context = _new_browser_context(browser, viewport)
    _set_default_navigation_timeout(context)
    return browser, context


def _launch_browser(
    playwright: Playwright,
    headless: bool,
    viewport: dict[str, int],
) -> Browser:
    return playwright.chromium.launch(
        headless=headless,
        args=_browser_args(viewport),
    )


def _browser_args(viewport: dict[str, int]) -> list[str]:
    return [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-infobars",
        "--disable-dev-shm-usage",
        f"--window-size={viewport['width']},{viewport['height']}",
    ]


def _new_browser_context(browser: Browser, viewport: dict[str, int]) -> BrowserContext:
    return browser.new_context(**_context_kwargs(viewport))


def _context_kwargs(viewport: dict[str, int]) -> dict[str, Any]:
    context_kwargs: dict[str, Any] = {
        "user_agent": random.choice(USER_AGENTS),
        "viewport": viewport,
        "locale": "it-CH",
        "timezone_id": "Europe/Zurich",
        "extra_http_headers": {"Accept-Language": "it-CH,it;q=0.9,en;q=0.8"},
    }
    if SESSION_FILE.exists():
        context_kwargs["storage_state"] = str(SESSION_FILE)
    return context_kwargs


def _set_default_navigation_timeout(context: BrowserContext) -> None:
    # Default for calls without an explicit timeout; scraper goto calls can
    # still pass their own timeout, which takes precedence.
    from scrapers.settings import PAGE_TIMEOUT_MS

    context.set_default_navigation_timeout(PAGE_TIMEOUT_MS)


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


def click_load_more(page: Page, btn_texts: list[str], count_js: str, max_clicks: int = 30, wait_ms: int = 3000) -> int:
    """Click visible load-more buttons until the result count stops growing."""
    previous_count = page.evaluate(count_js)
    unchanged_clicks = 0

    for click_number in range(1, max_clicks + 1):
        previous_count, unchanged_clicks, should_stop = _load_more_once(
            page, btn_texts, count_js, wait_ms, click_number, previous_count, unchanged_clicks
        )
        if should_stop:
            break

    return previous_count


def _load_more_once(
    page: Page, button_texts: list[str], count_js: str, wait_ms: int,
    click_number: int, previous_count: int, unchanged_clicks: int,
) -> tuple[int, int, bool]:
    button = _visible_load_more_button(page, button_texts)
    if button is None or not _click_load_more_button(button, click_number):
        return previous_count, unchanged_clicks, True

    new_count = _count_after_load_more(page, count_js, wait_ms)
    next_unchanged = _load_more_change_count(click_number, previous_count, new_count, unchanged_clicks)
    if next_unchanged >= 2:
        return previous_count, next_unchanged, True
    return new_count, next_unchanged, False


def _visible_load_more_button(page: Page, button_texts: list[str]) -> ElementHandle | None:
    for text in button_texts:
        button = _query_load_more_button(page, text)
        if button:
            return button
    return None


def _query_load_more_button(page: Page, text: str) -> ElementHandle | None:
    try:
        button = page.query_selector(f'button:has-text("{text}")')
        if button and button.is_visible():
            return button
    except Exception as error:
        print(f"    [load-more] query_selector('{text}') failed: {error}")
    return None


def _click_load_more_button(button: ElementHandle, click_number: int) -> bool:
    try:
        button.click()
        return True
    except Exception as error:
        print(f"    [load-more] btn.click() failed on click #{click_number}: {error}")
        return False


def _count_after_load_more(page: Page, count_js: str, wait_ms: int) -> int:
    page.wait_for_timeout(wait_ms)
    human_scroll(page)
    page.wait_for_timeout(1000)
    return page.evaluate(count_js)


def _load_more_change_count(
    click_number: int,
    previous_count: int,
    new_count: int,
    unchanged_clicks: int,
) -> int:
    delta = new_count - previous_count
    print(f"    [load-more] click #{click_number}: {previous_count}->{new_count} ({delta:+d})")
    if new_count <= previous_count:
        return unchanged_clicks + 1
    return 0


def dismiss_cookie_dialog(page: Page, site: str = "") -> str | None:
    """Close the cookie banner using domain rules plus fallback selectors."""
    from scrapers.page_guard import dismiss_cookies
    return dismiss_cookies(page, site)


def fetch_description(context: BrowserContext, url: str, max_chars: int = 3000) -> dict[str, str]:
    """Open a job page and return its cleaned description plus any email."""
    empty = {"description": "", "email": ""}
    if not _valid_description_url(url):
        return empty
    page = None
    try:
        page = _open_description_page(context, url)
        clean_text = _clean_description_text(_description_text(page))
        return _description_result(clean_text, max_chars)
    except Exception as e:
        print(f"  [DESC] error on {url[:60]}: {type(e).__name__}")
        return empty
    finally:
        _close_page(page)


def _valid_description_url(url: str) -> bool:
    return bool(url and url.startswith(("https://", "http://")))


def _open_description_page(context: BrowserContext, url: str) -> Page:
    page = new_stealth_page(context)
    page.goto(url, wait_until="domcontentloaded", timeout=20000)
    dismiss_cookie_dialog(page)
    page.wait_for_timeout(1500)
    return page


def _description_selectors() -> list[str]:
    return [
        "[data-cy='job-description']",
        "#jobDescriptionText",
        ".jobsearch-jobDescriptionText",
        ".job-description",
        ".job-detail__description",
        ".jobdescription",
        "article",
        "main",
    ]


def _description_text(page: Page) -> str:
    for selector in _description_selectors():
        text = _selector_text(page, selector)
        if len(text.strip()) > 100:
            return text
    return page.evaluate("() => document.body.innerText")


def _selector_text(page: Page, selector: str) -> str:
    element = page.query_selector(selector)
    if element:
        return element.inner_text()
    return ""


def _clean_description_text(description_text: str) -> str:
    lines = [line.strip() for line in description_text.splitlines() if line.strip()]
    return " | ".join(lines)


def _description_result(clean_text: str, max_chars: int) -> dict[str, str]:
    # Extract email from the full text before truncating the description.
    return {"description": clean_text[:max_chars], "email": extract_email(clean_text)}


def _close_page(page: Page | None) -> None:
    if not page:
        return
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
        return _retry_wrapper(func, max_attempts)
    return decorator


def _retry_wrapper(func: Callable[_P, _R], max_attempts: int | None) -> Callable[_P, _R]:
    @functools.wraps(func)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        return _run_with_retries(func, max_attempts, args, kwargs)
    return wrapper


def _run_with_retries(func: Callable[_P, _R], max_attempts: int | None, args: tuple[Any, ...], kwargs: dict[str, Any]) -> _R:
    attempts = _retry_attempts(max_attempts)
    for attempt in range(attempts):
        try:
            return func(*args, **kwargs)
        except Exception as error:
            status, reason = _classified_error(error)
            if _must_raise_retry(status, attempt, attempts):
                _raise_scrape_error(func.__name__, status, reason, attempt, error)
            _sleep_before_retry(func.__name__, status, attempt, attempts)
    raise RuntimeError("retry loop ended unexpectedly")


def _retry_attempts(max_attempts: int | None) -> int:
    from scrapers.settings import MAX_ATTEMPTS

    return min(max_attempts or MAX_ATTEMPTS, 3)


def _classified_error(error: Exception) -> tuple[str, str]:
    from scrapers.site_report import classify_exception

    return classify_exception(error)


def _must_raise_retry(status: str, attempt: int, attempts: int) -> bool:
    return status in ("browser_closed", "network_error") or attempt == attempts - 1


def _raise_scrape_error(
    function_name: str,
    status: str,
    reason: str,
    attempt: int,
    error: Exception,
) -> NoReturn:
    from scrapers.site_report import ScrapeError

    print(f"[ERROR] {function_name}: {status} - {reason}")
    raise ScrapeError(status, reason, attempt + 1) from error


def _sleep_before_retry(function_name: str, status: str, attempt: int, attempts: int) -> None:
    from scrapers.settings import RETRY_BACKOFF_S

    delay = RETRY_BACKOFF_S[min(attempt, len(RETRY_BACKOFF_S) - 1)]
    print(f"[RETRY] {function_name} attempt {attempt + 1}/{attempts} failed ({status}). Retrying in {delay}s...")
    time.sleep(delay)

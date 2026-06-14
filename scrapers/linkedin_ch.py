"""
Scraper for LinkedIn Jobs (www.linkedin.com/jobs), focused on Ticino, CH.

Public list URL, without login:
  https://www.linkedin.com/jobs/search/?keywords=&location=Ticino%2C+Switzerland&start=N

LinkedIn shows jobs publicly without login; a sign-in modal appears but does
not block the DOM. The guest API can also avoid the modal:
  https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?...&start=N

Confirmed DOM structure (2026-06), public page:
  li.base-card                    -> card wrapper
  a.base-card__full-link          -> anchor with job href
  h3.base-search-card__title      -> job title
  h4.base-search-card__subtitle a -> company
  span.job-search-card__location  -> city
  time[datetime]                  -> ISO YYYY-MM-DD date (datetime attribute)
  fallback: relative innerText such as "3 weeks ago"

Pagination: &start=0, &start=25, &start=50 ... (25 results per page).
MAX_PAGES = 5 -> 125 max jobs per run.

If an authwall/login redirect is detected, return [] without raising.
"""

import re
from datetime import date, timedelta

from playwright.sync_api import BrowserContext, Page

from scrapers import new_stealth_page, human_delay, human_scroll, retry
from scrapers.session import has_auth_state, auth_state_path
from scrapers.site_report import run_report, debug_artifacts
from job_filter import categorize_job


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_URL  = "https://www.linkedin.com"
LIST_URL  = "https://www.linkedin.com/jobs/search/"
MAX_PAGES = 5   # 25 results x 5 = 125 max

# Filter for Ticino, Switzerland.
_SEARCH_LOCATION = "Ticino%2C+Switzerland"

_BLOCKED_SIGNALS = (
    "authwall", "/login", "checkpoint/lg", "sign-in",
    "access denied", "403 forbidden",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_blocked(page: Page) -> bool:
    """Return True when LinkedIn shows an authwall or redirects to login."""
    try:
        url   = page.url.lower()
        title = page.title().lower()
        return any(s in url or s in title for s in _BLOCKED_SIGNALS)
    except Exception:
        return False


def _relative_to_date(text: str) -> str:
    """
    Convert relative or ISO dates to YYYY-MM-DD.
    Handles both the datetime attribute, already ISO, and text such as
    '3 weeks ago', '2 days ago', '1 month ago', 'just now'.
    """
    raw_text = text.strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}', raw_text):
        return raw_text[:10]
    lowered = raw_text.lower()
    if _means_today(lowered):
        return date.today().isoformat()
    return _relative_number_date(lowered)


def _means_today(lowered: str) -> bool:
    today_words = ("just", "now", "oggi")
    return not lowered or any(word in lowered for word in today_words)


def _relative_number_date(lowered: str) -> str:
    today = date.today()
    for pattern, multiplier in _relative_patterns():
        match = re.search(pattern, lowered)
        if match:
            return (today - timedelta(days=int(match.group(1)) * multiplier)).isoformat()
    if re.search(r'\d+\s*(hour|ora|ore)', lowered):
        return today.isoformat()
    return today.isoformat()


def _relative_patterns() -> tuple[tuple[str, int], ...]:
    return (
        (r'(\d+)\s*day', 1),
        (r'(\d+)\s*giorn', 1),
        (r'(\d+)\s*week', 7),
        (r'(\d+)\s*settiman', 7),
        (r'(\d+)\s*month', 30),
        (r'(\d+)\s*mes', 30),
    )


def _clean_url(href: str) -> str:
    """Remove LinkedIn tracking parameters, keeping only the path."""
    if not href:
        return ""
    # Drop query parameters such as position=, pageNum=, refId=, and trackingId=.
    return href.split("?")[0]


# ---------------------------------------------------------------------------
# JavaScript DOM extractor, executed in the browser.
# ---------------------------------------------------------------------------

_JS_EXTRACT = r"""() => {
    const results = [];
    const seen = new Set();

    // LinkedIn uses both <li class="base-card ..."> and <div class="base-card ...">
    // as wrappers for public list jobs.
    const cards = document.querySelectorAll('[class*="base-card"]');

    for (const card of cards) {
        // URL: main card anchor.
        const anchor = (
            card.querySelector('a.base-card__full-link') ||
            card.querySelector('a[href*="/jobs/view/"]') ||
            card.querySelector('a[href*="linkedin.com/jobs"]')
        );
        if (!anchor) continue;

        const href = anchor.getAttribute('href') || '';
        // Use the clean href as the deduplication key.
        const cleanHref = href.split('?')[0];
        if (!cleanHref || seen.has(cleanHref)) continue;
        seen.add(cleanHref);

        // Title.
        const titleEl = (
            card.querySelector('h3.base-search-card__title') ||
            card.querySelector('[class*="base-search-card__title"]') ||
            card.querySelector('h3') ||
            anchor
        );
        const title = (titleEl ? titleEl.innerText : '').trim();
        if (!title) continue;

        // Company.
        const companyEl = (
            card.querySelector('h4.base-search-card__subtitle a') ||
            card.querySelector('h4.base-search-card__subtitle') ||
            card.querySelector('[class*="base-search-card__subtitle"]') ||
            card.querySelector('h4')
        );
        // Some company names include " | domain.ch"; remove that suffix.
        const company = (companyEl ? companyEl.innerText : '').trim().replace(/\s*\|.*$/, '');

        // City.
        const cityEl = (
            card.querySelector('span.job-search-card__location') ||
            card.querySelector('[class*="job-search-card__location"]')
        );
        const city = (cityEl ? cityEl.innerText : '').trim();

        // Date: datetime attribute (ISO) or relative text.
        const timeEl = card.querySelector('time[datetime]');
        const dateRaw = timeEl
            ? (timeEl.getAttribute('datetime') || timeEl.innerText || '')
            : (card.querySelector('[class*="date"], [class*="listdate"]') || {innerText: ''}).innerText || '';

        results.push({
            href: cleanHref,
            title,
            company,
            city,
            dateRaw: dateRaw.trim(),
        });
    }
    return results;
}"""


# ---------------------------------------------------------------------------
# Main scraper.
# ---------------------------------------------------------------------------

@retry()
def scrape_linkedin_ch(context: BrowserContext) -> list[dict[str, str]]:
    """Use a saved session when available, otherwise scrape public pages."""
    auth_ctx = _create_auth_context(context)
    page = new_stealth_page(auth_ctx or context)
    try:
        return _scrape_all_pages(page, auth_ctx is not None)
    finally:
        _close_resources(page, auth_ctx)


def _scrape_all_pages(page: Page, using_auth: bool) -> list[dict[str, str]]:
    all_jobs: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for page_num in range(MAX_PAGES):
        if not _add_page_jobs(page, page_num, using_auth, seen_urls, all_jobs):
            break
    print(f"  [linkedin.ch] {len(all_jobs)} jobs found")
    return all_jobs


def _add_page_jobs(page: Page, page_num: int, using_auth: bool, seen_urls: set[str],
                   all_jobs: list[dict[str, str]]) -> bool:
    raw = _scrape_raw_page(page, page_num, using_auth)
    if not raw:
        return False
    new_jobs = _build_new_jobs(raw, seen_urls)
    if not new_jobs:
        print("  [linkedin.ch] No new jobs - stop")
        return False
    all_jobs.extend(new_jobs)
    print(f"  [linkedin.ch] {len(new_jobs)} new (total {len(all_jobs)})")
    human_delay(2.5, 5.0)
    return True


def _create_auth_context(context: BrowserContext) -> BrowserContext | None:
    if not has_auth_state("linkedin"):
        return None
    try:
        auth_ctx = context.browser.new_context(
            storage_state=str(auth_state_path("linkedin")),
            locale="it-CH", timezone_id="Europe/Zurich",
        )
        print("  [linkedin.ch] Using saved authenticated session")
        return auth_ctx
    except Exception as exc:
        print(f"  [linkedin.ch] Saved session unreadable ({exc}) - public mode")
        return None


def _scrape_raw_page(page: Page, page_num: int, using_auth: bool) -> list[dict[str, str]]:
    if not _open_search_page(page, page_num):
        return []
    if _blocked_after_open(page, using_auth):
        return []
    _dismiss_sign_in_modal(page)
    if not _wait_for_cards(page, page_num, using_auth):
        return []
    return _extract_raw_jobs(page, page_num)


def _open_search_page(page: Page, page_num: int) -> bool:
    start = page_num * 25
    print(f"  [linkedin.ch] Page {page_num + 1} (start={start})...")
    try:
        page.goto(_search_url(start), wait_until="networkidle", timeout=45000)
        return True
    except Exception:
        return _open_search_page_fallback(page, start)


def _search_url(start: int) -> str:
    return (
        f"{LIST_URL}?keywords=&location={_SEARCH_LOCATION}"
        f"&f_TPR=r2592000"
        f"&start={start}"
    )


def _open_search_page_fallback(page: Page, start: int) -> bool:
    try:
        page.goto(_search_url(start), wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        return True
    except Exception as exc:
        print(f"  [linkedin.ch] Navigation error: {exc}")
        return False


def _blocked_after_open(page: Page, using_auth: bool) -> bool:
    if not _is_blocked(page):
        return False
    shot = debug_artifacts(page, "linkedin_ch_authwall")
    run_report.set_status(
        "linkedin.ch", "requires_manual_login", _authwall_reason(using_auth),
        final_url=page.url, screenshot=shot)
    return True


def _authwall_reason(using_auth: bool) -> str:
    if using_auth:
        return "authwall despite saved session - probably expired: rerun python main.py --auth linkedin"
    return "authwall - for full access: python main.py --auth linkedin"


def _dismiss_sign_in_modal(page: Page) -> None:
    try:
        dismiss_btn = page.query_selector(
            'button[aria-label*="Dismiss"], '
            'button[aria-label*="Close"], '
            'button.modal__dismiss'
        )
        if dismiss_btn and dismiss_btn.is_visible():
            dismiss_btn.click()
            page.wait_for_timeout(500)
    except Exception:
        pass


def _wait_for_cards(page: Page, page_num: int, using_auth: bool) -> bool:
    for selector in _card_selectors():
        try:
            page.wait_for_selector(selector, timeout=8000)
            return True
        except Exception:
            pass
    _report_missing_cards(page, page_num, using_auth)
    return False


def _card_selectors() -> tuple[str, str, str]:
    return ('[class*="base-card"]', 'a[href*="/jobs/view/"]', 'ul.jobs-search__results-list')


def _report_missing_cards(page: Page, page_num: int, using_auth: bool) -> None:
    print(f"  [linkedin.ch] No card found (title={page.title()[:60]!r}) - stop")
    if page_num != 0:
        return
    shot = debug_artifacts(page, "linkedin_ch_nocards")
    hint = " - authenticated DOM may differ from public DOM" if using_auth else ""
    run_report.set_status(
        "linkedin.ch", "selector_broken",
        f"no card on page 1 (title={page.title()[:50]!r}){hint}",
        final_url=page.url, screenshot=shot)


def _extract_raw_jobs(page: Page, page_num: int) -> list[dict[str, str]]:
    human_scroll(page)
    page.wait_for_timeout(1500)
    raw = page.evaluate(_JS_EXTRACT)
    if raw:
        return raw
    print("  [linkedin.ch] Empty page - stop")
    if page_num == 0:
        debug_artifacts(page, "linkedin_ch_empty")
    return []


def _build_new_jobs(raw: list[dict[str, str]], seen_urls: set[str]) -> list[dict[str, str]]:
    jobs = [_build_job(item, seen_urls) for item in raw]
    return [job for job in jobs if job is not None]


def _build_job(item: dict[str, str], seen_urls: set[str]) -> dict[str, str] | None:
    job_url = _absolute_job_url(item.get("href", ""))
    title = item.get("title", "").strip()
    if not job_url or job_url in seen_urls or not title:
        return None
    seen_urls.add(job_url)
    return _job_from_item(item, title, job_url)


def _absolute_job_url(job_url: str) -> str:
    if job_url.startswith("/"):
        return BASE_URL + job_url
    if job_url.startswith("http"):
        return job_url
    return ""


def _job_from_item(item: dict[str, str], title: str, job_url: str) -> dict[str, str]:
    return {
        "title": title,
        "company": item.get("company", "").strip(),
        "city": item.get("city", "").strip(),
        "date": _relative_to_date(item.get("dateRaw", "")),
        "url": job_url,
        "category": categorize_job(title),
        "source": "linkedin.ch",
    }


def _close_resources(page: Page, auth_ctx: BrowserContext | None) -> None:
    try:
        page.close()
    except Exception:
        pass
    if auth_ctx:
        try:
            auth_ctx.close()
        except Exception:
            pass

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
    today = date.today()
    t = text.strip()

    # datetime attribute already uses ISO YYYY-MM-DD.
    if re.match(r'^\d{4}-\d{2}-\d{2}', t):
        return t[:10]

    t_lower = t.lower()
    if not t_lower or "just" in t_lower or "now" in t_lower or "oggi" in t_lower:
        return today.isoformat()

    # "X hours ago" / "X ore fa".
    if re.search(r'\d+\s*(hour|ora|ore)', t_lower):
        return today.isoformat()

    # "X days ago" / "X giorni fa".
    m = re.search(r'(\d+)\s*day', t_lower)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    m = re.search(r'(\d+)\s*giorn', t_lower)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()

    # "X weeks ago" / "X settimane fa".
    m = re.search(r'(\d+)\s*week', t_lower)
    if m:
        return (today - timedelta(weeks=int(m.group(1)))).isoformat()
    m = re.search(r'(\d+)\s*settiman', t_lower)
    if m:
        return (today - timedelta(weeks=int(m.group(1)))).isoformat()

    # "X months ago" / "X mesi fa".
    m = re.search(r'(\d+)\s*month', t_lower)
    if m:
        return (today - timedelta(days=int(m.group(1)) * 30)).isoformat()
    m = re.search(r'(\d+)\s*mes', t_lower)
    if m:
        return (today - timedelta(days=int(m.group(1)) * 30)).isoformat()

    return today.isoformat()


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
    """
    Use a manually saved session when available, otherwise scrape public pages.
    Never attempts automatic login.
    """
    all_jobs  = []
    seen_urls = set()

    auth_ctx = None
    if has_auth_state("linkedin"):
        try:
            auth_ctx = context.browser.new_context(
                storage_state=str(auth_state_path("linkedin")),
                locale="it-CH", timezone_id="Europe/Zurich",
            )
            print("  [linkedin.ch] Using saved authenticated session")
        except Exception as e:
            print(f"  [linkedin.ch] Saved session unreadable ({e}) - public mode")
            auth_ctx = None

    page = new_stealth_page(auth_ctx or context)
    try:
        for page_num in range(MAX_PAGES):
            start = page_num * 25
            url = (
                f"{LIST_URL}?keywords=&location={_SEARCH_LOCATION}"
                f"&f_TPR=r2592000"   # last 30 days
                f"&start={start}"
            )
            print(f"  [linkedin.ch] Page {page_num + 1} (start={start})...")

            try:
                page.goto(url, wait_until="networkidle", timeout=45000)
            except Exception:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)
                except Exception as e:
                    print(f"  [linkedin.ch] Navigation error: {e}")
                    break

            # Report authwalls/login redirects; do not bypass them.
            if _is_blocked(page):
                shot = debug_artifacts(page, "linkedin_ch_authwall")
                if auth_ctx:
                    reason = ("authwall despite saved session - probably expired: "
                              "rerun python scraper.py --auth linkedin")
                else:
                    reason = "authwall - for full access: python scraper.py --auth linkedin"
                run_report.set_status("linkedin.ch", "requires_manual_login", reason,
                                      final_url=page.url, screenshot=shot)
                break

            # Close non-blocking sign-in modals when present.
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

            # Wait for cards to be present in the DOM.
            card_loaded = False
            for wait_sel in [
                '[class*="base-card"]',
                'a[href*="/jobs/view/"]',
                'ul.jobs-search__results-list',
            ]:
                try:
                    page.wait_for_selector(wait_sel, timeout=8000)
                    card_loaded = True
                    break
                except Exception:
                    pass

            if not card_loaded:
                print(f"  [linkedin.ch] No card found (title={page.title()[:60]!r}) - stop")
                if page_num == 0:
                    shot = debug_artifacts(page, "linkedin_ch_nocards")
                    hint = (" - note: authenticated DOM differs from the public DOM;"
                            " selectors need adjustment") if auth_ctx else ""
                    run_report.set_status(
                        "linkedin.ch", "selector_broken",
                        f"no card on page 1 (title={page.title()[:50]!r}){hint}",
                        final_url=page.url, screenshot=shot)
                break

            human_scroll(page)
            page.wait_for_timeout(1500)

            raw = page.evaluate(_JS_EXTRACT)
            if not raw:
                print(f"  [linkedin.ch] Empty page - stop")
                if page_num == 0:
                    debug_artifacts(page, "linkedin_ch_empty")
                break

            new_jobs = []
            for item in raw:
                job_url = item.get("href", "")
                if not job_url or job_url in seen_urls:
                    continue
                seen_urls.add(job_url)

                title = item.get("title", "").strip()
                if not title:
                    continue

                # Absolute URL.
                if job_url.startswith("/"):
                    job_url = BASE_URL + job_url
                elif not job_url.startswith("http"):
                    continue

                new_jobs.append({
                    "title":    title,
                    "company":  item.get("company", "").strip(),
                    "city":     item.get("city", "").strip(),
                    "date":     _relative_to_date(item.get("dateRaw", "")),
                    "url":      job_url,
                    "category": categorize_job(title),
                    "source":   "linkedin.ch",
                })

            if not new_jobs:
                print(f"  [linkedin.ch] No new jobs - stop")
                break

            all_jobs.extend(new_jobs)
            print(f"  [linkedin.ch] {len(new_jobs)} new (total {len(all_jobs)})")
            human_delay(2.5, 5.0)

        print(f"  [linkedin.ch] {len(all_jobs)} jobs found")
        return all_jobs
    finally:
        try:
            page.close()
        except Exception:
            pass
        if auth_ctx:
            try:
                auth_ctx.close()
            except Exception:
                pass

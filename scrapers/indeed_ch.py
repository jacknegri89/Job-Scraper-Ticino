# Scraper for Indeed Switzerland (ch.indeed.com), focused on Ticino jobs.
#
# Strategy: keyword searches in public mode, without a session.
# Indeed shows page 1 without login; page 2 requires registration.
# Different keywords produce N x 15 jobs, deduplicated by job key (jk).
#
# URL: https://ch.indeed.com/jobs?q=<keyword>&l=Ticino&radius=50
# Confirmed DOM structure (2026-06):
#   a[data-jk]                   -> job link
#   span[id^="jobTitle"]         -> title
#   [data-testid="company-name"] -> company
#   [data-testid="text-location"]-> city

import re
from datetime import date, timedelta

from playwright.sync_api import BrowserContext, Page

from scrapers import new_stealth_page, human_delay, human_scroll, retry
from scrapers.page_guard import detect_auth_gate, detect_block, dismiss_cookies
from scrapers.site_report import run_report, debug_artifacts
from job_filter import categorize_job

BASE_URL = "https://ch.indeed.com"
LIST_URL = "https://ch.indeed.com/jobs"

# Each keyword runs one page-1 search, usually about 15 results.
_KEYWORDS = [
    "", "operaio", "magazziniere", "tecnico", "addetto",
    "autista", "elettricista", "assemblatore", "logistica",
    "informatico", "produzione", "cameriere", "commesso",
]


def _relative_to_date(text: str) -> str:
    today = date.today()
    lowered = text.lower().strip()
    if _is_today_text(lowered):
        return today.isoformat()
    if "ieri" in lowered or "yesterday" in lowered:
        return (today - timedelta(days=1)).isoformat()
    if re.search(r'\d+\s*or[ae]', lowered) or "hour" in lowered:
        return today.isoformat()
    matched_days = _extract_day_count(lowered)
    if matched_days is not None:
        return (today - timedelta(days=matched_days)).isoformat()
    if "30+" in lowered or "mese" in lowered or "month" in lowered:
        return (today - timedelta(days=30)).isoformat()
    return today.isoformat()


def _is_today_text(lowered: str) -> bool:
    return not lowered or any(word in lowered for word in ("oggi", "just posted", "appena", "now"))


def _extract_day_count(lowered: str) -> int | None:
    for pattern in (r'(\d+)\+?\s*giorni?\s*fa', r'(\d+)\+?\s*days?\s*ago'):
        match = re.search(pattern, lowered)
        if match:
            return int(match.group(1))
    return None


# Extract jobs through JavaScript; this is more reliable than chained CSS selectors.
_JS_EXTRACT = r"""() => {
    const results = [];
    const seen = new Set();
    const anchors = document.querySelectorAll('a[data-jk]');
    for (const a of anchors) {
        const jk = a.getAttribute('data-jk');
        if (!jk || jk.length < 8 || seen.has(jk)) continue;
        seen.add(jk);

        const titleEl = (
            a.querySelector('span[id^="jobTitle"]') ||
            a.querySelector('span[title]') ||
            a.querySelector('span')
        );
        const title = (titleEl
            ? (titleEl.getAttribute('title') || titleEl.innerText)
            : a.innerText).trim();
        if (!title) continue;

        const li = a.closest('li');
        if (!li) continue;

        const companyEl = li.querySelector('[data-testid="company-name"]');
        const cityEl    = li.querySelector('[data-testid="text-location"]');
        const dateEl    = li.querySelector('[class*="date"]:not([class*="job"]), span[class*="date"]');

        results.push({
            jk,
            title,
            company: companyEl ? companyEl.innerText.trim() : '',
            city:    cityEl    ? cityEl.innerText.trim()    : '',
            dateRaw: dateEl    ? dateEl.innerText.trim()    : '',
        });
    }
    return results;
}"""


def _scrape_keyword(page: Page, keyword: str, seen_jk: set[str],
                    cookie_done: list[bool]) -> list[dict[str, str]]:
    if not _open_keyword_page(page, keyword):
        return []
    _handle_cookie_once(page, cookie_done)
    if _blocked_or_gated(page):
        return []
    _wait_for_cards(page)
    raw = _extract_raw_jobs(page)
    if not raw:
        return []
    return _build_jobs(raw, seen_jk)


def _open_keyword_page(page: Page, keyword: str) -> bool:
    label = repr(keyword) if keyword else "'(all)'"
    print(f"  [indeed.ch] Searching: {label}")
    try:
        page.goto(_keyword_url(keyword), wait_until="networkidle", timeout=40000)
        return True
    except Exception:
        return _open_keyword_page_fallback(page, keyword)


def _keyword_url(keyword: str) -> str:
    return f"{LIST_URL}?q={keyword.replace(' ', '+')}&l=Ticino&radius=50"


def _open_keyword_page_fallback(page: Page, keyword: str) -> bool:
    try:
        page.goto(_keyword_url(keyword), wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(2000)
        return True
    except Exception as exc:
        print(f"  [indeed.ch] Navigation failed ({type(exc).__name__}) - skip")
        return False


def _handle_cookie_once(page: Page, cookie_done: list[bool]) -> None:
    if cookie_done[0]:
        return
    dismiss_cookies(page, "indeed.ch")
    page.wait_for_timeout(1500)
    cookie_done[0] = True


def _blocked_or_gated(page: Page) -> bool:
    if detect_block(page):
        print("  [indeed.ch] Anti-bot block detected - stop")
        return True
    return detect_auth_gate(page) is not None


def _wait_for_cards(page: Page) -> None:
    for selector in ("[data-jk]", "#mosaic-provider-jobcards", ".job_seen_beacon"):
        try:
            page.wait_for_selector(selector, timeout=5000)
            return
        except Exception:
            pass


def _extract_raw_jobs(page: Page) -> list[dict[str, str]]:
    human_scroll(page)
    page.wait_for_timeout(1000)
    return page.evaluate(_JS_EXTRACT)


def _build_jobs(raw: list[dict[str, str]], seen_jk: set[str]) -> list[dict[str, str]]:
    jobs = [_build_job(item, seen_jk) for item in raw]
    return [job for job in jobs if job is not None]


def _build_job(item: dict[str, str], seen_jk: set[str]) -> dict[str, str] | None:
    job_key = item.get("jk", "")
    title = item.get("title", "").strip()
    if not job_key or job_key in seen_jk or not title:
        return None
    seen_jk.add(job_key)
    return _job_from_item(item, job_key, title)


def _job_from_item(item: dict[str, str], job_key: str, title: str) -> dict[str, str]:
    return {
        "title": title,
        "company": item.get("company", "").strip(),
        "city": item.get("city", "").strip(),
        "date": _relative_to_date(item.get("dateRaw", "")),
        "url": f"{BASE_URL}/viewjob?jk={job_key}",
        "category": categorize_job(title),
        "source": "indeed.ch",
    }


@retry()
def scrape_indeed_ch(context: BrowserContext) -> list[dict[str, str]]:
    all_jobs: list[dict[str, str]] = []
    seen_jk: set[str] = set()
    cookie_done = [False]   # Mutable flag shared with the keyword helper.

    page = new_stealth_page(context)
    try:
        return _scrape_keywords(page, seen_jk, cookie_done, all_jobs)
    finally:
        try:
            page.close()
        except Exception:
            pass


def _scrape_keywords(
    page: Page,
    seen_jk: set[str],
    cookie_done: list[bool],
    all_jobs: list[dict[str, str]],
) -> list[dict[str, str]]:
    for keyword in _KEYWORDS:
        _add_keyword_jobs(page, keyword, seen_jk, cookie_done, all_jobs)
    print(f"  [indeed.ch] {len(all_jobs)} jobs found")
    return all_jobs


def _add_keyword_jobs(
    page: Page,
    keyword: str,
    seen_jk: set[str],
    cookie_done: list[bool],
    all_jobs: list[dict[str, str]],
) -> None:
    batch = _scrape_keyword(page, keyword, seen_jk, cookie_done)
    if batch:
        all_jobs.extend(batch)
        print(f"  [indeed.ch]   +{len(batch)} new (total {len(all_jobs)})")
    human_delay(1.5, 3.0)

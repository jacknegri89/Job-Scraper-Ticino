"""
Scraper for Adecco Switzerland (www.adecco.com/it-ch), focused on Ticino jobs.

www.adecco.ch redirects to adecco.com/de-ch; the Italian version is adecco.com/it-ch.
Jobs are loaded by React, so data is read from the React fiber (jobSearchResults[]).
URL: https://www.adecco.com/it-ch/trovare-lavoro?jobsearch-title=&location=Ticino
"""

import re
import unicodedata
from datetime import date

from playwright.sync_api import BrowserContext, Page

from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, retry
from scrapers.site_report import run_report, debug_artifacts
from job_filter import categorize_job

LIST_URL = "https://www.adecco.com/it-ch/trovare-lavoro"
BASE_URL = "https://www.adecco.com"
MAX_PAGES = 5
_PAGE_SIZE = 20


def _slugify(text: str) -> str:
    """Convert text to an adecco.com-style URL slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text).strip("-")
    return text


# React stores the full job payload in the first result card's fiber props.
_JS_EXTRACT = r"""() => {
    function getReactProps(el) {
        const key = Object.keys(el).find(k => k.startsWith('__reactFiber'));
        if (!key) return null;
        let fiber = el[key];
        while (fiber) {
            if (fiber.memoizedProps && fiber.memoizedProps.jobSearchResults) return fiber.memoizedProps;
            fiber = fiber.return;
        }
        return null;
    }
    const card = document.querySelector('article.JobSearch_job-search-card__XtCBC');
    if (!card) return null;
    const props = getReactProps(card);
    if (!props || !props.jobSearchResults) return null;
    return props.jobSearchResults.map(j => ({
        jobId:    j.jobId    || '',
        title:    j.jobTitle || '',
        city:     j.cityName || j.jobLocation || '',
        state:    j.stateName || '',
        date:     j.postedDate || j.jobCreationDate || '',
    }));
}"""


def _page_url(page_num: int) -> str:
    if page_num == 0:
        return f"{LIST_URL}?jobsearch-title=&location=Ticino"
    return f"{LIST_URL}?jobsearch-title=&location=Ticino&offset={page_num * _PAGE_SIZE}"


def _open_results_page(page: Page, page_url: str, page_num: int) -> None:
    print(f"  [adecco.ch] Page {page_num + 1}...")
    try:
        page.goto(page_url, wait_until="networkidle", timeout=45000)
    except Exception:
        page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)


def _handle_first_page_cookie(page: Page, page_num: int) -> None:
    if page_num == 0:
        dismiss_cookie_dialog(page)
        page.wait_for_timeout(2000)


def _wait_for_cards(page: Page, page_num: int) -> bool:
    try:
        page.wait_for_selector("article.JobSearch_job-search-card__XtCBC", timeout=10000)
        return True
    except Exception:
        print("  [adecco.ch] No card found - stop")
        if page_num == 0:
            _report_missing_cards(page)
        return False


def _report_missing_cards(page: Page) -> None:
    shot = debug_artifacts(page, "adecco_ch_nocards")
    run_report.set_status(
        "adecco.ch", "selector_broken",
        "React card not found on page 1 (class changed?)",
        final_url=page.url, screenshot=shot)


def _extract_raw_jobs(page: Page, page_num: int) -> list[dict[str, str]] | None:
    human_scroll(page)
    page.wait_for_timeout(1200)
    raw = page.evaluate(_JS_EXTRACT)
    if raw:
        return raw
    print("  [adecco.ch] No React fiber data - stop")
    if page_num == 0:
        _report_missing_react_data(page)
    return None


def _report_missing_react_data(page: Page) -> None:
    shot = debug_artifacts(page, "adecco_ch_nofiber")
    run_report.set_status(
        "adecco.ch", "selector_broken",
        "React fiber jobSearchResults not found",
        final_url=page.url, screenshot=shot)


def _build_job(item: dict[str, str], seen_ids: set[str]) -> dict[str, str] | None:
    job_id = item.get("jobId", "").strip()
    title = item.get("title", "").strip()
    if not job_id or job_id in seen_ids or not title:
        return None
    seen_ids.add(job_id)
    return _job_from_item(item, job_id, title)


def _job_from_item(item: dict[str, str], job_id: str, title: str) -> dict[str, str]:
    city = item.get("city", "").strip()
    state = item.get("state", "").strip()
    raw_date = item.get("date", "")
    return {
        "title": title,
        "company": "Adecco",
        "city": city,
        "date": raw_date[:10] if raw_date else date.today().isoformat(),
        "url": _job_url(title, city, state, job_id),
        "category": categorize_job(title),
        "source": "adecco.ch",
    }


def _job_url(title: str, city: str, state: str, job_id: str) -> str:
    slug = _slugify(f"{title} {city} {state}")
    return f"{BASE_URL}/it-ch/ricerca-lavoro/{slug}/{job_id.lower()}"


def _build_batch(raw: list[dict[str, str]], seen_ids: set[str]) -> list[dict[str, str]]:
    jobs = [_build_job(item, seen_ids) for item in raw]
    return [job for job in jobs if job is not None]


def _scrape_page(page: Page, page_num: int, seen_ids: set[str]) -> tuple[list[dict[str, str]], int]:
    _open_results_page(page, _page_url(page_num), page_num)
    _handle_first_page_cookie(page, page_num)
    if not _wait_for_cards(page, page_num):
        return [], 0
    raw = _extract_raw_jobs(page, page_num)
    if raw is None:
        return [], 0
    return _build_batch(raw, seen_ids), len(raw)


@retry()
def scrape_adecco_ch(context: BrowserContext) -> list[dict[str, str]]:
    page = new_stealth_page(context)
    try:
        return _scrape_all_pages(page)
    finally:
        page.close()


def _scrape_all_pages(page: Page) -> list[dict[str, str]]:
    all_jobs: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for page_num in range(MAX_PAGES):
        if not _add_page_jobs(page, page_num, seen_ids, all_jobs):
            break
    print(f"  [adecco.ch] {len(all_jobs)} jobs found")
    return all_jobs


def _add_page_jobs(
    page: Page,
    page_num: int,
    seen_ids: set[str],
    all_jobs: list[dict[str, str]],
) -> bool:
    batch, raw_count = _scrape_page(page, page_num, seen_ids)
    if not batch:
        return False
    all_jobs.extend(batch)
    print(f"  [adecco.ch] {len(batch)} new (total {len(all_jobs)})")
    if raw_count < _PAGE_SIZE:
        return False
    human_delay(2.0, 4.0)
    return True

"""
Scraper for JobScout24 Switzerland (www.jobscout24.ch)

List URL: /de/jobs/ticino/?p=N (German UI, Italian content)
About 162 jobs across 9 pages. Kept separate from jobs.ch despite the shared JobCloud group.
Relative dates use German units: "1 T" = 1 day, "1 W" = 1 week, "1+M" = 1+ month.
"""

import re
from datetime import date, timedelta

from playwright.sync_api import BrowserContext, Page

from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, retry
from job_filter import categorize_job

BASE_URL  = "https://www.jobscout24.ch"
LIST_URL  = "https://www.jobscout24.ch/de/jobs/ticino/"
MAX_PAGES = 15
_JS_EXTRACT = r"""() => {
    const results = [];
    const anchors = document.querySelectorAll('a[href^="/de/job/"]');
    const seen = new Set();

    for (const a of anchors) {
        const href = a.getAttribute('href');
        if (!href || seen.has(href)) continue;
        seen.add(href);

        const li = a.closest('li');
        if (!li) continue;

        const title = a.innerText.trim();
        if (!title) continue;

        const firstP = li.querySelector('p');
        let company = '', city = '';
        if (firstP) {
            const parts = firstP.innerText.split(',').map(s => s.trim()).filter(Boolean);
            company = parts[0] || '';
            city    = parts[1] || '';
        }

        const lines = li.innerText.split('\n').map(s => s.trim()).filter(Boolean);
        const dateRaw = lines[lines.length - 1] || '';

        results.push({ title, href, company, city, dateRaw });
    }
    return results;
}"""


def _relative_to_date(text: str) -> str:
    """
    Convert German relative date units to YYYY-MM-DD:
      '1 T'  -> 1 day ago
      '6 T'  -> 6 days ago
      '1 W'  -> 1 week ago
      '2 W'  -> 2 weeks ago
      '1+M' -> about 30+ days ago
    """
    match = re.search(r'(\d+)\+?\s*([TWM])', text)
    if not match:
        return date.today().isoformat()
    return _date_from_match(int(match.group(1)), match.group(2))


def _date_from_match(amount: int, unit: str) -> str:
    today = date.today()
    if unit == 'T':
        return (today - timedelta(days=amount)).isoformat()
    if unit == 'W':
        return (today - timedelta(weeks=amount)).isoformat()
    if unit == 'M':
        return (today - timedelta(days=amount * 30)).isoformat()
    return today.isoformat()


def _extract_jobs(page: Page) -> list[dict[str, str]]:
    return page.evaluate(_JS_EXTRACT)


@retry()
def scrape_jobscout24_ch(context: BrowserContext) -> list[dict[str, str]]:
    all_jobs: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    page = new_stealth_page(context)
    try:
        for page_num in range(1, MAX_PAGES + 1):
            if not _add_page_jobs(page, page_num, seen_urls, all_jobs):
                break
        print(f"  [jobscout24.ch] {len(all_jobs)} jobs found")
        return all_jobs
    finally:
        page.close()


def _add_page_jobs(
    page: Page,
    page_num: int,
    seen_urls: set[str],
    all_jobs: list[dict[str, str]],
) -> bool:
    _open_page(page, page_num)
    raw = _extract_jobs(page)
    new_jobs = _build_new_jobs(raw, seen_urls)
    if not new_jobs:
        return False
    all_jobs.extend(new_jobs)
    print(f"  [jobscout24.ch] {len(new_jobs)} new (total {len(all_jobs)})")
    human_delay(2.0, 4.0)
    return True


def _open_page(page: Page, page_num: int) -> None:
    print(f"  [jobscout24.ch] Page {page_num}...")
    page.goto(f"{LIST_URL}?p={page_num}", wait_until="domcontentloaded", timeout=30000)
    if page_num == 1:
        dismiss_cookie_dialog(page, "jobscout24.ch")
        page.wait_for_timeout(1500)
    human_scroll(page)
    page.wait_for_timeout(1000)


def _build_new_jobs(raw: list[dict[str, str]], seen_urls: set[str]) -> list[dict[str, str]]:
    jobs = [_build_job(item, seen_urls) for item in raw]
    return [job for job in jobs if job is not None]


def _build_job(item: dict[str, str], seen_urls: set[str]) -> dict[str, str] | None:
    job_url = _absolute_url(item.get("href", ""))
    title = item.get("title", "").strip()
    if not title or job_url in seen_urls:
        return None
    seen_urls.add(job_url)
    return _job_from_item(item, title, job_url)


def _absolute_url(href: str) -> str:
    return BASE_URL + href if href.startswith("/") else href


def _job_from_item(item: dict[str, str], title: str, job_url: str) -> dict[str, str]:
    return {
        "title": title,
        "company": item.get("company", ""),
        "city": item.get("city", ""),
        "date": _relative_to_date(item.get("dateRaw", "")),
        "url": job_url,
        "category": categorize_job(title),
        "source": "jobscout24.ch",
    }

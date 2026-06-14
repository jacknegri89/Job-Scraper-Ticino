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


def _relative_to_date(text: str) -> str:
    """
    Convert German relative date units to YYYY-MM-DD:
      '1 T'  -> 1 day ago
      '6 T'  -> 6 days ago
      '1 W'  -> 1 week ago
      '2 W'  -> 2 weeks ago
      '1+M' -> about 30+ days ago
    """
    today = date.today()
    m = re.search(r'(\d+)\+?\s*([TWM])', text)
    if not m:
        return today.isoformat()
    n, unit = int(m.group(1)), m.group(2)
    if unit == 'T':
        return (today - timedelta(days=n)).isoformat()
    if unit == 'W':
        return (today - timedelta(weeks=n)).isoformat()
    if unit == 'M':
        return (today - timedelta(days=n * 30)).isoformat()
    return today.isoformat()


def _extract_jobs(page: Page) -> list[dict[str, str]]:
    return page.evaluate(r"""() => {
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

            // First <p> in li: "Company, City"
            const firstP = li.querySelector('p');
            let company = '', city = '';
            if (firstP) {
                const parts = firstP.innerText.split(',').map(s => s.trim()).filter(Boolean);
                company = parts[0] || '';
                city    = parts[1] || '';
            }

            // Relative date: last non-empty line in li
            const lines = li.innerText.split('\n').map(s => s.trim()).filter(Boolean);
            const dateRaw = lines[lines.length - 1] || '';

            results.push({ title, href, company, city, dateRaw });
        }
        return results;
    }""")


@retry()
def scrape_jobscout24_ch(context: BrowserContext) -> list[dict[str, str]]:
    all_jobs  = []
    seen_urls = set()
    page = new_stealth_page(context)
    try:
        for page_num in range(1, MAX_PAGES + 1):
            url = f"{LIST_URL}?p={page_num}"
            print(f"  [jobscout24.ch] Page {page_num}...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            if page_num == 1:
                dismiss_cookie_dialog(page, "jobscout24.ch")
                page.wait_for_timeout(1500)

            human_scroll(page)
            page.wait_for_timeout(1000)

            raw = _extract_jobs(page)
            if not raw:
                break

            new_jobs = []
            for item in raw:
                href = item.get("href", "")
                url_job = BASE_URL + href if href.startswith("/") else href
                title   = item.get("title", "").strip()
                if not title or url_job in seen_urls:
                    continue
                seen_urls.add(url_job)
                new_jobs.append({
                    "title":    title,
                    "company":  item.get("company", ""),
                    "city":     item.get("city", ""),
                    "date":     _relative_to_date(item.get("dateRaw", "")),
                    "url":      url_job,
                    "category": categorize_job(title),
                    "source":   "jobscout24.ch",
                })

            if not new_jobs:
                break   # Repeated page: real pagination ended.
            all_jobs.extend(new_jobs)
            print(f"  [jobscout24.ch] {len(new_jobs)} new (total {len(all_jobs)})")
            human_delay(2.0, 4.0)

        print(f"  [jobscout24.ch] {len(all_jobs)} jobs found")
        return all_jobs
    finally:
        page.close()

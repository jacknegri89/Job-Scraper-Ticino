"""
Scraper for Adecco Switzerland (www.adecco.com/it-ch), focused on Ticino jobs.

www.adecco.ch redirects to adecco.com/de-ch; the Italian version is adecco.com/it-ch.
Jobs are loaded by React, so data is read from the React fiber (jobSearchResults[]).
URL: https://www.adecco.com/it-ch/trovare-lavoro?jobsearch-title=&location=Ticino
"""

import re
import unicodedata
from datetime import date

from playwright.sync_api import BrowserContext

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


@retry()
def scrape_adecco_ch(context: BrowserContext) -> list[dict[str, str]]:
    all_jobs = []
    seen_ids = set()

    page = new_stealth_page(context)
    try:
        for page_num in range(MAX_PAGES):
            offset   = page_num * _PAGE_SIZE
            page_url = (
                f"{LIST_URL}?jobsearch-title=&location=Ticino&offset={offset}"
                if page_num > 0
                else f"{LIST_URL}?jobsearch-title=&location=Ticino"
            )
            print(f"  [adecco.ch] Page {page_num + 1}...")

            try:
                page.goto(page_url, wait_until="networkidle", timeout=45000)
            except Exception:
                page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(4000)

            if page_num == 0:
                dismiss_cookie_dialog(page)
                page.wait_for_timeout(2000)

            try:
                page.wait_for_selector("article.JobSearch_job-search-card__XtCBC", timeout=10000)
            except Exception:
                print(f"  [adecco.ch] No card found - stop")
                if page_num == 0:
                    shot = debug_artifacts(page, "adecco_ch_nocards")
                    run_report.set_status(
                        "adecco.ch", "selector_broken",
                        "React card not found on page 1 (class changed?)",
                        final_url=page.url, screenshot=shot)
                break

            human_scroll(page)
            page.wait_for_timeout(1200)

            raw = page.evaluate(_JS_EXTRACT)
            if not raw:
                print(f"  [adecco.ch] No React fiber data - stop")
                if page_num == 0:
                    shot = debug_artifacts(page, "adecco_ch_nofiber")
                    run_report.set_status(
                        "adecco.ch", "selector_broken",
                        "React fiber jobSearchResults not found",
                        final_url=page.url, screenshot=shot)
                break

            batch = []
            for item in raw:
                job_id = item.get("jobId", "").strip()
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                title = item.get("title", "").strip()
                if not title:
                    continue

                city  = item.get("city",  "").strip()
                state = item.get("state", "").strip()
                slug  = _slugify(f"{title} {city} {state}")
                url   = f"{BASE_URL}/it-ch/ricerca-lavoro/{slug}/{job_id.lower()}"

                raw_date = item.get("date", "")
                job_date = raw_date[:10] if raw_date else date.today().isoformat()

                batch.append({
                    "title":    title,
                    "company":  "Adecco",
                    "city":     city,
                    "date":     job_date,
                    "url":      url,
                    "category": categorize_job(title),
                    "source":   "adecco.ch",
                })

            if not batch:
                break

            all_jobs.extend(batch)
            print(f"  [adecco.ch] {len(batch)} new (total {len(all_jobs)})")

            # Fewer than _PAGE_SIZE results means this is the last page.
            if len(raw) < _PAGE_SIZE:
                break

            human_delay(2.0, 4.0)

        print(f"  [adecco.ch] {len(all_jobs)} jobs found")
        return all_jobs
    finally:
        page.close()

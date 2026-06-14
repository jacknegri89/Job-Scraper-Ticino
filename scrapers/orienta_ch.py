"""
Scraper for Orienta Switzerland (www.orienta.ch)

List URL: /it/orienta-job/offerte-di-lavoro.html?page=N
49 jobs across about 5 pages, all in Ticino (Lugano/Manno branch).
Structure: article > a[href*='/offerta-di-lavoro/'] > h2
           "Data" / "Sede" rows appear as label/value pairs in the text.
           Live "Sede" format: "Svizzera, Ticino, City"; keep the last part.
"""

from datetime import datetime

from playwright.sync_api import BrowserContext, Page

from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, retry
from job_filter import categorize_job

BASE_URL  = "https://www.orienta.ch"
LIST_URL  = "https://www.orienta.ch/it/orienta-job/offerte-di-lavoro.html"
MAX_PAGES = 10


def _parse_date(raw: str) -> str:
    """Convert strings like '09/06/2026 Nuovo' to '2026-06-09'."""
    try:
        return datetime.strptime(raw.split()[0], "%d/%m/%Y").strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        return raw


def _extract_jobs(page: Page) -> list[dict[str, str]]:
    jobs = []
    for article in page.query_selector_all("article"):
        link_el = article.query_selector("a[href*='/offerta-di-lavoro/']")
        if not link_el:
            continue
        href = link_el.get_attribute("href") or ""
        url = (BASE_URL + href) if href.startswith("/") else href
        h2 = link_el.query_selector("h2")
        title = (h2.inner_text() if h2 else link_el.inner_text()).strip()
        if not title:
            continue

        # Site labels "Data" and "Sede" appear as separate rows before values.
        lines = [l.strip() for l in article.inner_text().splitlines() if l.strip()]
        city = date = ""
        for i, line in enumerate(lines):
            if line == "Sede" and i + 1 < len(lines):
                parts = lines[i + 1].split(",")
                # Live value format is "Svizzera, Ticino, Chiasso"; city is last.
                city = parts[-1].strip()
            elif line == "Data" and i + 1 < len(lines):
                date = _parse_date(lines[i + 1])

        jobs.append({
            "title":    title,
            "company":  "Orienta SA",
            "city":     city,
            "date":     date,
            "url":      url,
            "category": categorize_job(title),
            "source":   "orienta.ch",
        })
    return jobs


@retry()
def scrape_orienta_ch(context: BrowserContext) -> list[dict[str, str]]:
    all_jobs  = []
    seen_urls = set()
    page = new_stealth_page(context)
    try:
        for page_num in range(1, MAX_PAGES + 1):
            url = f"{LIST_URL}?page={page_num}"
            print(f"  [orienta.ch] Page {page_num}...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            if page_num == 1:
                dismiss_cookie_dialog(page)
                page.wait_for_timeout(1500)

            human_scroll(page)
            page.wait_for_timeout(1000)

            jobs = _extract_jobs(page)
            if not jobs:
                break
            new_jobs = [j for j in jobs if j["url"] not in seen_urls]
            if not new_jobs:
                break   # Repeated page: real pagination ended.
            for j in new_jobs:
                seen_urls.add(j["url"])
            all_jobs.extend(new_jobs)
            print(f"  [orienta.ch] {len(new_jobs)} new (total {len(all_jobs)})")
            human_delay(2.0, 4.0)

        return all_jobs
    finally:
        page.close()

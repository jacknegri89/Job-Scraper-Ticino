"""
Scraper for Gi Group Switzerland (ch.gigroup.com/it/posizioni-aperte/)

Live structure:
- Card:   .ggp-job-item
- Title:  h2.ggp-job-item-title
- City:   .job-item-meta-row with .bi-geo-alt -> "City, Province, Canton"
- Date:   .job-item-meta-row with .bi-calendar2-minus -> "DD/MM/YYYY"
- URL:    a.ggp-job-item-detail-btn -> relative, base https://ch.gigroup.com
- Pagination: ?npage=N
"""

from datetime import datetime

from playwright.sync_api import BrowserContext, Page

from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, retry
from job_filter import categorize_job

BASE_URL = "https://ch.gigroup.com"
LIST_URL = "https://ch.gigroup.com/it/posizioni-aperte/?npage={page}"
MAX_PAGES = 20  # Safety limit; stops earlier when the page is empty.


def _parse_date(raw: str) -> str:
    """Convert 'DD/MM/YYYY' to 'YYYY-MM-DD', or return the original string."""
    try:
        return datetime.strptime(raw.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return raw.strip()


def _extract_jobs_from_page(page: Page) -> list[dict[str, str]]:
    cards = page.query_selector_all(".ggp-job-item")
    jobs: list[dict[str, str]] = []
    for card in cards:
        try:
            job = _job_from_card(card)
            if job:
                jobs.append(job)
        except Exception as exc:
            print(f"[WARN] gigroup.ch card error: {exc}")
            continue
    return jobs


def _job_from_card(card: object) -> dict[str, str] | None:
    title = _card_title(card)
    url = _card_url(card)
    if not title or not url:
        return None
    city, job_date = _card_location_and_date(card)
    return {
        "title": title,
        "company": "Gi Group SA",
        "city": city,
        "date": job_date,
        "url": url,
        "category": categorize_job(title),
        "source": "gigroup.ch",
    }


def _card_title(card: object) -> str:
    title_el = card.query_selector("h2.ggp-job-item-title")
    return title_el.inner_text().strip() if title_el else ""


def _card_url(card: object) -> str:
    url_el = card.query_selector("a.ggp-job-item-detail-btn")
    href = url_el.get_attribute("href") if url_el else ""
    return BASE_URL + href if href and href.startswith("/") else href


def _card_location_and_date(card: object) -> tuple[str, str]:
    city = ""
    job_date = ""
    for row in card.query_selector_all(".job-item-meta-row"):
        city, job_date = _read_meta_row(row, city, job_date)
    return city, job_date


def _read_meta_row(row: object, city: str, job_date: str) -> tuple[str, str]:
    icon = row.query_selector("span.bi")
    if not icon:
        return city, job_date
    icon_class = icon.get_attribute("class") or ""
    text = _meta_text(row)
    if "bi-geo-alt" in icon_class:
        return text.split(",")[0].strip(), job_date
    if "bi-calendar2-minus" in icon_class:
        return city, _parse_date(text)
    return city, job_date


def _meta_text(row: object) -> str:
    text_el = row.query_selector("div:last-child span")
    return text_el.inner_text().strip() if text_el else ""


@retry()
def scrape_gigroup_ch(context: BrowserContext) -> list[dict[str, str]]:
    all_jobs: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    page = new_stealth_page(context)
    try:
        for page_num in range(1, MAX_PAGES + 1):
            if not _add_page_jobs(page, page_num, seen_urls, all_jobs):
                break
        return all_jobs
    finally:
        page.close()


def _add_page_jobs(page: Page, page_num: int, seen_urls: set[str],
                   all_jobs: list[dict[str, str]]) -> bool:
    _open_page(page, page_num)
    jobs = _extract_jobs_from_page(page)
    new_jobs = [job for job in jobs if job["url"] not in seen_urls]
    if not jobs or not new_jobs:
        return False
    seen_urls.update(job["url"] for job in new_jobs)
    all_jobs.extend(new_jobs)
    print(f"  [gigroup.ch] {len(new_jobs)} new (total {len(all_jobs)})")
    human_delay(2.0, 5.0)
    return True


def _open_page(page: Page, page_num: int) -> None:
    print(f"  [gigroup.ch] Page {page_num}")
    page.goto(LIST_URL.format(page=page_num), wait_until="domcontentloaded", timeout=30000)
    dismiss_cookie_dialog(page)
    page.wait_for_timeout(2000)
    human_scroll(page)

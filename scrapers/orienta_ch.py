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
    jobs: list[dict[str, str]] = []
    for article in page.query_selector_all("article"):
        job = _job_from_article(article)
        if job:
            jobs.append(job)
    return jobs


def _job_from_article(article: object) -> dict[str, str] | None:
    link_el = article.query_selector("a[href*='/offerta-di-lavoro/']")
    if not link_el:
        return None
    title = _title_from_link(link_el)
    if not title:
        return None
    city, job_date = _city_and_date(article)
    return _job_payload(link_el, title, city, job_date)


def _job_payload(link_el: object, title: str, city: str, job_date: str) -> dict[str, str]:
    return {
        "title": title,
        "company": "Orienta SA",
        "city": city,
        "date": job_date,
        "url": _absolute_url(link_el.get_attribute("href") or ""),
        "category": categorize_job(title),
        "source": "orienta.ch",
    }


def _title_from_link(link_el: object) -> str:
    heading = link_el.query_selector("h2")
    return (heading.inner_text() if heading else link_el.inner_text()).strip()


def _absolute_url(href: str) -> str:
    return BASE_URL + href if href.startswith("/") else href


def _city_and_date(article: object) -> tuple[str, str]:
    city = ""
    job_date = ""
    lines = [line.strip() for line in article.inner_text().splitlines() if line.strip()]
    for index, line in enumerate(lines):
        city, job_date = _read_label_value(lines, index, line, city, job_date)
    return city, job_date


def _read_label_value(
    lines: list[str],
    index: int,
    line: str,
    city: str,
    job_date: str,
) -> tuple[str, str]:
    if index + 1 >= len(lines):
        return city, job_date
    if line == "Sede":
        return lines[index + 1].split(",")[-1].strip(), job_date
    if line == "Data":
        return city, _parse_date(lines[index + 1])
    return city, job_date


@retry()
def scrape_orienta_ch(context: BrowserContext) -> list[dict[str, str]]:
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
    jobs = _extract_jobs(page)
    new_jobs = [job for job in jobs if job["url"] not in seen_urls]
    if not jobs or not new_jobs:
        return False
    seen_urls.update(job["url"] for job in new_jobs)
    all_jobs.extend(new_jobs)
    print(f"  [orienta.ch] {len(new_jobs)} new (total {len(all_jobs)})")
    human_delay(2.0, 4.0)
    return True


def _open_page(page: Page, page_num: int) -> None:
    print(f"  [orienta.ch] Page {page_num}...")
    page.goto(f"{LIST_URL}?page={page_num}", wait_until="domcontentloaded", timeout=30000)
    if page_num == 1:
        dismiss_cookie_dialog(page)
        page.wait_for_timeout(1500)
    human_scroll(page)
    page.wait_for_timeout(1000)

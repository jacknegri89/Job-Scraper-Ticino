import urllib.parse

from playwright.sync_api import BrowserContext, Page

from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, retry
from job_filter import SEARCH_TERMS, categorize_job

BASE_URL   = "https://www.jobs.ch"
SEARCH_URL = "https://www.jobs.ch/en/vacancies/?term={term}&location=ticino&page={page}"
MAX_PAGES  = 20   # Safety limit; stops earlier when the page is empty.


def _extract_jobs_from_page(page: Page) -> list[dict[str, str]]:
    jobs: list[dict[str, str]] = []
    cards = page.query_selector_all('a[data-cy="job-link"]')
    for card in cards:
        try:
            job = _job_from_card(card)
            if job:
                jobs.append(job)
        except Exception as exc:
            print(f"[WARN] jobs.ch card error: {exc}")
    return jobs


def _job_from_card(card: object) -> dict[str, str] | None:
    title = card.get_attribute("title") or ""
    href = card.get_attribute("href") or ""
    url = f"{BASE_URL}{href}" if href.startswith("/") else href
    if not title or not url:
        return None
    return _build_job(card, title, url)


def _build_job(card: object, title: str, url: str) -> dict[str, str]:
    paragraphs = card.query_selector_all("p")
    company_el = card.query_selector("p[class*='fw_bol']")
    return {
        "title": title,
        "company": company_el.text_content().strip() if company_el else "",
        "city": _paragraph_text(paragraphs, 1),
        "date": _paragraph_text(paragraphs, 0),
        "url": url,
        "category": categorize_job(title),
        "source": "jobs.ch",
    }


def _paragraph_text(paragraphs: list[object], index: int) -> str:
    if len(paragraphs) <= index:
        return ""
    return paragraphs[index].text_content().strip()


@retry()
def scrape_jobs_ch(
    context: BrowserContext,
    search_terms: list[str] | None = None,
) -> list[dict[str, str]]:
    terms = search_terms or SEARCH_TERMS
    all_jobs: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    page = new_stealth_page(context)
    try:
        for term in terms:
            _scrape_term(page, term, seen_urls, all_jobs)
        print(f"[jobs.ch] Raw total: {len(all_jobs)}")
        return all_jobs
    finally:
        page.close()


def _scrape_term(
    page: Page,
    term: str,
    seen_urls: set[str],
    all_jobs: list[dict[str, str]],
) -> None:
    print(f"[jobs.ch] Searching: '{term}'")
    for page_num in range(1, MAX_PAGES + 1):
        if not _add_page_jobs(page, term, page_num, seen_urls, all_jobs):
            break


def _add_page_jobs(
    page: Page,
    term: str,
    page_num: int,
    seen_urls: set[str],
    all_jobs: list[dict[str, str]],
) -> bool:
    url = SEARCH_URL.format(term=urllib.parse.quote_plus(term), page=page_num)
    try:
        jobs = _load_page_jobs(page, url)
    except Exception as exc:
        print(f"[WARN] {url}: {exc}")
        return False
    return _add_new_jobs(jobs, page_num, seen_urls, all_jobs)


def _load_page_jobs(page: Page, url: str) -> list[dict[str, str]]:
    page.goto(url, timeout=30_000, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    dismiss_cookie_dialog(page)
    human_scroll(page)
    human_delay(3.0, 7.0)
    return _extract_jobs_from_page(page)


def _add_new_jobs(
    jobs: list[dict[str, str]],
    page_num: int,
    seen_urls: set[str],
    all_jobs: list[dict[str, str]],
) -> bool:
    if not jobs:
        return False
    new_jobs = [job for job in jobs if job["url"] not in seen_urls]
    if not new_jobs:
        return False
    seen_urls.update(job["url"] for job in new_jobs)
    all_jobs.extend(new_jobs)
    print(f"  page {page_num}: {len(new_jobs)} new ({len(jobs)} total)")
    return True

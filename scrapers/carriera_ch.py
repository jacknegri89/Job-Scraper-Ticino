from playwright.sync_api import BrowserContext, Page

from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, retry
from job_filter import categorize_job

LIST_URL  = "https://www.carriera.ch/offerte/annunci-offerte-lavoro_0_0_{page}.html"
MAX_PAGES = 50  # Safety limit; stops earlier when a page adds no new jobs.


def _extract_jobs_from_page(page: Page) -> list[dict[str, str]]:
    jobs: list[dict[str, str]] = []
    rows = page.query_selector_all("tr")
    for row in rows:
        cells = row.query_selector_all("td")
        if len(cells) != 6:
            continue
        try:
            job = _job_from_cells(cells)
            if job:
                jobs.append(job)
        except Exception as exc:
            print(f"[WARN] carriera.ch row error: {exc}")
    return jobs


def _job_from_cells(cells: list[object]) -> dict[str, str] | None:
    title_link = cells[2].query_selector("a")
    if not title_link:
        return None
    title = title_link.text_content().strip()
    url = _absolute_url(title_link.get_attribute("href") or "")
    if not title or not url:
        return None
    return _build_job(cells, title, url)


def _absolute_url(url: str) -> str:
    return url if url.startswith("http") else f"https://www.carriera.ch{url}"


def _build_job(cells: list[object], title: str, url: str) -> dict[str, str]:
    company_img = cells[1].query_selector("img")
    company = (company_img.get_attribute("alt") or "").strip() if company_img else cells[1].text_content().strip()
    return {
        "title": title,
        "company": company,
        "city": cells[3].text_content().strip(),
        "date": cells[0].text_content().strip(),
        "url": url,
        "category": categorize_job(title),
        "source": "carriera.ch",
    }


@retry()
def scrape_carriera_ch(context: BrowserContext) -> list[dict[str, str]]:
    all_jobs: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    page = new_stealth_page(context)
    try:
        for page_num in range(MAX_PAGES):
            if not _add_page_jobs(page, page_num, seen_urls, all_jobs):
                break
        print(f"[carriera.ch] Raw total: {len(all_jobs)}")
        return all_jobs
    finally:
        page.close()


def _add_page_jobs(
    page: Page,
    page_num: int,
    seen_urls: set[str],
    all_jobs: list[dict[str, str]],
) -> bool:
    url = LIST_URL.format(page=page_num)
    print(f"[carriera.ch] Page {page_num + 1}")
    try:
        jobs = _load_page_jobs(page, url)
    except Exception as exc:
        print(f"[WARN] {url}: {exc}")
        return False
    return _add_new_jobs(jobs, seen_urls, all_jobs)


def _load_page_jobs(page: Page, url: str) -> list[dict[str, str]]:
    page.goto(url, timeout=30_000, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    dismiss_cookie_dialog(page)
    human_scroll(page)
    human_delay(3.0, 7.0)
    return _extract_jobs_from_page(page)


def _add_new_jobs(
    jobs: list[dict[str, str]],
    seen_urls: set[str],
    all_jobs: list[dict[str, str]],
) -> bool:
    new_jobs = [job for job in jobs if job["url"] not in seen_urls]
    if not jobs or not new_jobs:
        return False
    seen_urls.update(job["url"] for job in new_jobs)
    all_jobs.extend(new_jobs)
    print(f"  {len(new_jobs)} new ({len(jobs)} total)")
    return True

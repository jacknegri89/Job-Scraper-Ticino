"""
Scraper for Randstad Switzerland (www.randstad.ch/it/lavoro/re-ticino/)

Live structure:
- List URL: /it/lavoro/re-ticino/ -> 38 Ticino jobs
- Title:    a[href with UUID] > h3
- City:     "City, Ticino" line in card text
- Date:     "D. Month YYYY" line, for example "9. Giugno 2026"
- URL:      relative link, base https://www.randstad.ch
- Company:  always "Randstad SA"
"""

from playwright.sync_api import BrowserContext, Page

from scrapers import new_stealth_page, human_delay, human_scroll, dismiss_cookie_dialog, click_load_more, retry
from job_filter import categorize_job

BASE_URL = "https://www.randstad.ch"
LIST_URL = "https://www.randstad.ch/it/lavoro/re-ticino/"

# JS extraction is more reliable than CSS selectors with dynamic classes.
_JS_EXTRACT = """
() => {
  const MONTHS_IT = {
    'gennaio':1,'febbraio':2,'marzo':3,'aprile':4,'maggio':5,'giugno':6,
    'luglio':7,'agosto':8,'settembre':9,'ottobre':10,'novembre':11,'dicembre':12
  };
  const links = Array.from(document.querySelectorAll('a[href*="/it/lavoro/"]'))
    .filter(a => /[a-f0-9]{8}-[a-f0-9]{4}/.test(a.getAttribute('href') || ''));

  return links.map(a => {
    const li = a.closest('li');
    const lines = (li ? li.innerText.trim() : '')
      .split('\\n').map(s => s.trim()).filter(Boolean);

    const title = (a.querySelector('h3') || {}).innerText || '';

    // "City, Canton" line, detected by comma plus space.
    const cityLine = lines.find(l => l.includes(', ')) || '';
    const city = cityLine.split(',')[0].trim();

    // Date line -> "D. Month YYYY".
    const dateLine = lines.find(l => /\\d+\\.\\s+\\w+\\s+\\d{4}/.test(l)) || '';
    const dm = dateLine.match(/(\\d+)\\.\\s+(\\w+)\\s+(\\d{4})/);
    let date = dateLine;
    if (dm) {
      const month = MONTHS_IT[dm[2].toLowerCase()];
      if (month) {
        date = dm[3] + '-' + String(month).padStart(2, '0') + '-' + dm[1].padStart(2, '0');
      }
    }

    return {
      title: title.trim(),
      city:  city,
      date:  date,
      url:   'https://www.randstad.ch' + a.getAttribute('href'),
    };
  }).filter(j => j.title && j.url);
}
"""


@retry()
def scrape_randstad_ch(context: BrowserContext) -> list[dict[str, str]]:
    page = new_stealth_page(context)
    try:
        all_jobs = _scrape_jobs(page)
    finally:
        page.close()
    human_delay(2.0, 4.0)
    return all_jobs


def _scrape_jobs(page: Page) -> list[dict[str, str]]:
    _open_list_page(page)
    _load_all_cards(page)
    jobs = _build_jobs(page.evaluate(_JS_EXTRACT))
    print(f"  [randstad.ch] {len(jobs)} jobs found")
    return jobs


def _open_list_page(page: Page) -> None:
    print("  [randstad.ch] Loading Ticino jobs...")
    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=30000)
    dismiss_cookie_dialog(page)
    page.wait_for_timeout(2000)
    human_scroll(page)
    page.wait_for_timeout(1500)


def _load_all_cards(page: Page) -> None:
    dismiss_cookie_dialog(page)
    total = click_load_more(
        page,
        btn_texts=["Visualizza altri", "Mostra altri", "Carica altri"],
        count_js=_count_js(),
    )
    print(f"  [randstad.ch] {total} job links in the DOM after load-more")


def _count_js() -> str:
    return (
        "Array.from(document.querySelectorAll('a[href*=\"/it/lavoro/\"]'))"
        ".filter(a => /[a-f0-9]{8}-[a-f0-9]{4}/.test(a.getAttribute('href') || '')).length"
    )


def _build_jobs(raw_jobs: list[dict[str, str]]) -> list[dict[str, str]]:
    jobs = [_build_job(job) for job in raw_jobs]
    return [job for job in jobs if job is not None]


def _build_job(raw_job: dict[str, str]) -> dict[str, str] | None:
    title = raw_job.get("title", "").strip()
    url = raw_job.get("url", "").strip()
    if not title or not url:
        return None
    return {
        "title": title,
        "company": "Randstad SA",
        "city": raw_job.get("city", "").strip(),
        "date": raw_job.get("date", ""),
        "url": url,
        "category": categorize_job(title),
        "source": "randstad.ch",
    }

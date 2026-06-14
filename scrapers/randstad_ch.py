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

from playwright.sync_api import BrowserContext

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
    all_jobs = []
    page = new_stealth_page(context)
    try:
        print("  [randstad.ch] Loading Ticino jobs...")
        page.goto(LIST_URL, wait_until="domcontentloaded", timeout=30000)
        dismiss_cookie_dialog(page)
        page.wait_for_timeout(2000)

        human_scroll(page)
        page.wait_for_timeout(1500)

        # OneTrust can appear late and intercept load-more clicks, so run a
        # second dismissal pass right before clicking.
        dismiss_cookie_dialog(page)

        _COUNT_JS = (
            "Array.from(document.querySelectorAll('a[href*=\"/it/lavoro/\"]'))"
            ".filter(a => /[a-f0-9]{8}-[a-f0-9]{4}/.test(a.getAttribute('href') || '')).length"
        )
        total = click_load_more(
            page,
            btn_texts=["Visualizza altri", "Mostra altri", "Carica altri"],
            count_js=_COUNT_JS,
        )
        print(f"  [randstad.ch] {total} job links in the DOM after load-more")

        jobs_raw = page.evaluate(_JS_EXTRACT)

        for job in jobs_raw:
            title = job.get("title", "").strip()
            city  = job.get("city",  "").strip()
            url   = job.get("url",   "").strip()
            if not title or not url:
                continue
            all_jobs.append({
                "title":    title,
                "company":  "Randstad SA",
                "city":     city,
                "date":     job.get("date", ""),
                "url":      url,
                "category": categorize_job(title),
                "source":   "randstad.ch",
            })

        print(f"  [randstad.ch] {len(all_jobs)} jobs found")
    finally:
        page.close()

    human_delay(2.0, 4.0)
    return all_jobs

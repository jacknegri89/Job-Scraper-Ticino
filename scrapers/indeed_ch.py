# Scraper for Indeed Switzerland (ch.indeed.com), focused on Ticino jobs.
#
# Strategy: keyword searches in public mode, without a session.
# Indeed shows page 1 without login; page 2 requires registration.
# Different keywords produce N x 15 jobs, deduplicated by job key (jk).
#
# URL: https://ch.indeed.com/jobs?q=<keyword>&l=Ticino&radius=50
# Confirmed DOM structure (2026-06):
#   a[data-jk]                   -> job link
#   span[id^="jobTitle"]         -> title
#   [data-testid="company-name"] -> company
#   [data-testid="text-location"]-> city

import re
from datetime import date, timedelta

from playwright.sync_api import BrowserContext, Page

from scrapers import new_stealth_page, human_delay, human_scroll, retry
from scrapers.page_guard import detect_auth_gate, detect_block, dismiss_cookies
from scrapers.site_report import run_report, debug_artifacts
from job_filter import categorize_job

BASE_URL = "https://ch.indeed.com"
LIST_URL = "https://ch.indeed.com/jobs"

# Each keyword runs one page-1 search, usually about 15 results.
_KEYWORDS = [
    "", "operaio", "magazziniere", "tecnico", "addetto",
    "autista", "elettricista", "assemblatore", "logistica",
    "informatico", "produzione", "cameriere", "commesso",
]


def _relative_to_date(text: str) -> str:
    # Convert relative date text, including Italian site strings, to YYYY-MM-DD.
    today = date.today()
    t = text.lower().strip()
    if not t or "oggi" in t or "just posted" in t or "appena" in t or "now" in t:
        return today.isoformat()
    if "ieri" in t or "yesterday" in t:
        return (today - timedelta(days=1)).isoformat()
    if re.search(r'\d+\s*or[ae]', t) or "hour" in t:
        return today.isoformat()
    m = re.search(r'(\d+)\+?\s*giorni?\s*fa', t)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    m = re.search(r'(\d+)\+?\s*days?\s*ago', t)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    if "30+" in t or "mese" in t or "month" in t:
        return (today - timedelta(days=30)).isoformat()
    return today.isoformat()


# Extract jobs through JavaScript; this is more reliable than chained CSS selectors.
_JS_EXTRACT = r"""() => {
    const results = [];
    const seen = new Set();
    const anchors = document.querySelectorAll('a[data-jk]');
    for (const a of anchors) {
        const jk = a.getAttribute('data-jk');
        if (!jk || jk.length < 8 || seen.has(jk)) continue;
        seen.add(jk);

        const titleEl = (
            a.querySelector('span[id^="jobTitle"]') ||
            a.querySelector('span[title]') ||
            a.querySelector('span')
        );
        const title = (titleEl
            ? (titleEl.getAttribute('title') || titleEl.innerText)
            : a.innerText).trim();
        if (!title) continue;

        const li = a.closest('li');
        if (!li) continue;

        const companyEl = li.querySelector('[data-testid="company-name"]');
        const cityEl    = li.querySelector('[data-testid="text-location"]');
        const dateEl    = li.querySelector('[class*="date"]:not([class*="job"]), span[class*="date"]');

        results.push({
            jk,
            title,
            company: companyEl ? companyEl.innerText.trim() : '',
            city:    cityEl    ? cityEl.innerText.trim()    : '',
            dateRaw: dateEl    ? dateEl.innerText.trim()    : '',
        });
    }
    return results;
}"""


def _scrape_keyword(
    page: Page,
    keyword: str,
    seen_jk: set[str],
    cookie_done: list[bool],
) -> list[dict[str, str]]:
    q = keyword.replace(" ", "+")
    url = f"{LIST_URL}?q={q}&l=Ticino&radius=50"
    label = repr(keyword) if keyword else "'(all)'"
    print(f"  [indeed.ch] Searching: {label}")

    try:
        page.goto(url, wait_until="networkidle", timeout=40000)
    except Exception:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"  [indeed.ch] Navigation failed ({type(e).__name__}) - skip")
            return []

    # Close the cookie banner only once per session.
    if not cookie_done[0]:
        dismiss_cookies(page, "indeed.ch")
        page.wait_for_timeout(1500)
        cookie_done[0] = True

    if detect_block(page):
        print("  [indeed.ch] Anti-bot block detected - stop")
        return []
    if detect_auth_gate(page):
        return []

    # Wait for cards to be present in the DOM.
    for sel in ["[data-jk]", "#mosaic-provider-jobcards", ".job_seen_beacon"]:
        try:
            page.wait_for_selector(sel, timeout=5000)
            break
        except Exception:
            pass

    human_scroll(page)
    page.wait_for_timeout(1000)

    raw = page.evaluate(_JS_EXTRACT)
    if not raw:
        return []

    jobs = []
    for item in raw:
        jk = item.get("jk", "")
        if not jk or jk in seen_jk:
            continue
        seen_jk.add(jk)
        title = item.get("title", "").strip()
        if not title:
            continue
        jobs.append({
            "title":    title,
            "company":  item.get("company", "").strip(),
            "city":     item.get("city",    "").strip(),
            "date":     _relative_to_date(item.get("dateRaw", "")),
            "url":      f"{BASE_URL}/viewjob?jk={jk}",
            "category": categorize_job(title),
            "source":   "indeed.ch",
        })
    return jobs


@retry()
def scrape_indeed_ch(context: BrowserContext) -> list[dict[str, str]]:
    all_jobs    = []
    seen_jk     = set()
    cookie_done = [False]   # Mutable flag shared with the keyword helper.

    page = new_stealth_page(context)
    try:
        for kw in _KEYWORDS:
            batch = _scrape_keyword(page, kw, seen_jk, cookie_done)
            if batch:
                all_jobs.extend(batch)
                print(f"  [indeed.ch]   +{len(batch)} new (total {len(all_jobs)})")
            human_delay(1.5, 3.0)

        print(f"  [indeed.ch] {len(all_jobs)} jobs found")
        return all_jobs
    finally:
        try:
            page.close()
        except Exception:
            pass

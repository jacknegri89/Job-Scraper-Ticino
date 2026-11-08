"""Scrapers for Indeed Italia and LinkedIn Italia (Lombardy).

Both are read the way a visitor reads them: public search pages, no login, no captcha
solving. If a portal shows a block or a login wall the scraper stops and says so.

Checked on 2026-11-08 and NOT used, because they refuse or hide their results from an
automated browser (nothing is done to get around that):
  subito.it    "Access Denied" (HTTP 403)
  infojobs.it  an empty page, no listings in the HTML
Not implemented yet: jobrapido.it, randstad.it, adecco.it (need their own page analysis).

Each scraper reports an explicit status:
  ok             listings were read
  no_results     the portal said, in its own words, that nothing matches
  selector_broken the page loaded but no listing cards were found and it is not a
                  "no results" page (the portal probably changed its layout)
  blocked / requires_auth   a block or login wall was detected
"""

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote_plus, urlencode

from playwright.sync_api import BrowserContext, Page

from job_filter import SEARCH_TERMS, categorize_job
from scrapers import human_delay, human_scroll, new_stealth_page, retry
from scrapers import settings
from scrapers.indeed_ch import _relative_to_date as indeed_relative_date
from scrapers.linkedin_ch import _JS_EXTRACT as LINKEDIN_CARDS_JS
from scrapers.linkedin_ch import _is_blocked as linkedin_is_blocked
from scrapers.linkedin_ch import _relative_to_date as linkedin_relative_date
from scrapers.page_guard import detect_auth_gate, detect_block, dismiss_cookies
from scrapers.site_report import debug_artifacts, run_report

INDEED_SITE = "indeed.it"
INDEED_BASE_URL = "https://it.indeed.com"
LINKEDIN_SITE = "linkedin.it"
LINKEDIN_LIST_URL = "https://www.linkedin.com/jobs/search/"
DEFAULT_REGION_TEXT = "Lombardia"

MAX_SEARCH_TERMS = 12
KM_PER_MILE = 1.609
INDEED_RADIUS_STEPS_KM = (5, 10, 15, 25, 50, 100)
LINKEDIN_RADIUS_STEPS_MILES = (5, 10, 25, 50, 75, 100)
MAX_SALARY_TEXT_LENGTH = 120

_NO_RESULTS_MARKERS = (
    "non ha prodotto risultati", "nessun risultato", "nessuna offerta", "no results found", "non abbiamo trovato",
)

# Indeed cards, read in the page. The salary line is the card line that shows a currency or RAL.
_INDEED_CARDS_JS = r"""() => {
    const results = [];
    const seen = new Set();
    for (const anchor of document.querySelectorAll('a[data-jk]')) {
        const jk = anchor.getAttribute('data-jk');
        if (!jk || jk.length < 8 || seen.has(jk)) continue;
        seen.add(jk);
        const titleEl = anchor.querySelector('span[id^="jobTitle"]') || anchor.querySelector('span[title]') || anchor.querySelector('span');
        const title = (titleEl ? (titleEl.getAttribute('title') || titleEl.innerText) : anchor.innerText).trim();
        const card = anchor.closest('li');
        if (!title || !card) continue;
        const companyEl = card.querySelector('[data-testid="company-name"]');
        const cityEl = card.querySelector('[data-testid="text-location"]');
        const dateEl = card.querySelector('[class*="date"]:not([class*="job"]), span[class*="date"]');
        const lines = card.innerText.split('\n').map(line => line.trim());
        const salary = lines.find(line => /(€|EUR|RAL)/i.test(line) && /\d/.test(line)) || '';
        results.push({
            jk, title, salary,
            company: companyEl ? companyEl.innerText.trim() : '',
            city: cityEl ? cityEl.innerText.trim() : '',
            dateRaw: dateEl ? dateEl.innerText.trim() : '',
        });
    }
    return results;
}"""

_INDEED_CARD_SELECTORS = ("[data-jk]", "#mosaic-provider-jobcards", ".job_seen_beacon")
_LINKEDIN_CARD_SELECTORS = ('[class*="base-card"]', 'a[href*="/jobs/view/"]', "ul.jobs-search__results-list")


@dataclass
class _Portal:
    """What differs between portals; the search loop itself is shared."""

    site: str
    url_for_term: Callable[[str], str]
    cards_js: str
    card_selectors: tuple[str, ...]
    make_job: Callable[[dict], dict | None]
    is_blocked: Callable[[Page], bool]


# ---------------------------------------------------------------- search area

def search_terms() -> list[str]:
    """The user's search terms, without blanks, limited so a scan stays short."""
    terms = [term.strip() for term in SEARCH_TERMS if term.strip()]
    return terms[:MAX_SEARCH_TERMS]


def _next_step_up(value: float, steps: tuple[int, ...]) -> int:
    for step in steps:
        if value <= step:
            return step
    return steps[-1]


def indeed_search_url(term: str, place: str, radius_km: float | None) -> str:
    """Indeed Italia search URL. Without a starting point the whole region is searched."""
    params = {"q": term, "l": place or DEFAULT_REGION_TEXT}
    if place and radius_km:
        params["radius"] = _next_step_up(radius_km, INDEED_RADIUS_STEPS_KM)
    return f"{INDEED_BASE_URL}/jobs?{urlencode(params)}"


def linkedin_search_url(term: str, place: str, radius_km: float | None) -> str:
    """LinkedIn jobs search URL (listings of the last 30 days)."""
    location = f"{place}, {DEFAULT_REGION_TEXT}, Italia"
    if not place:
        location = f"{DEFAULT_REGION_TEXT}, Italia"
    url = f"{LINKEDIN_LIST_URL}?keywords={quote_plus(term)}&location={quote_plus(location)}&f_TPR=r2592000"
    if place and radius_km:
        miles = _next_step_up(radius_km / KM_PER_MILE, LINKEDIN_RADIUS_STEPS_MILES)
        url += f"&distance={miles}"
    return url


# ---------------------------------------------------------------- job builders

def build_indeed_job(item: dict) -> dict | None:
    job_key = str(item.get("jk") or "")
    title = str(item.get("title") or "").strip()
    if not job_key or not title:
        return None
    return {
        "title": title,
        "company": str(item.get("company") or "").strip(),
        "city": str(item.get("city") or "").strip(),
        "date": indeed_relative_date(str(item.get("dateRaw") or "")),
        "url": f"{INDEED_BASE_URL}/viewjob?jk={job_key}",
        "category": categorize_job(title),
        "source": INDEED_SITE,
        "salary_text": str(item.get("salary") or "").strip()[:MAX_SALARY_TEXT_LENGTH],
    }


def build_linkedin_job(item: dict) -> dict | None:
    href = str(item.get("href") or "")
    title = str(item.get("title") or "").strip()
    if not href.startswith("https://") or not title:
        return None
    return {
        "title": title,
        "company": str(item.get("company") or "").strip(),
        "city": str(item.get("city") or "").strip(),
        "date": linkedin_relative_date(str(item.get("dateRaw") or "")),
        "url": href,
        "category": categorize_job(title),
        "source": LINKEDIN_SITE,
    }


# ---------------------------------------------------------------- shared search loop

def _search_all_terms(page: Page, portal: _Portal) -> list[dict]:
    terms = search_terms()
    jobs: list[dict] = []
    seen_urls: set[str] = set()
    outcomes: list[str] = []
    cookie_done = [False]
    for term in terms:
        outcome, term_jobs = _search_one_term(page, portal, term, cookie_done)
        outcomes.append(outcome)
        _add_new_jobs(jobs, seen_urls, term_jobs)
        if outcome == "stopped":
            break
        human_delay(1.5, 3.0)
    _report_outcome(portal.site, jobs, outcomes)
    print(f"  [{portal.site}] {len(jobs)} jobs found")
    return jobs


def _add_new_jobs(jobs: list[dict], seen_urls: set[str], term_jobs: list[dict]) -> None:
    for job in term_jobs:
        if job["url"] not in seen_urls:
            seen_urls.add(job["url"])
            jobs.append(job)


def _search_one_term(page: Page, portal: _Portal, term: str, cookie_done: list[bool]) -> tuple[str, list[dict]]:
    """Return (outcome, jobs). Outcomes: found, no_results, unreadable, navigation_failed, stopped."""
    print(f"  [{portal.site}] Searching: {term!r}")
    if not _open_page(page, portal, term):
        return "navigation_failed", []
    _dismiss_cookies_once(page, portal.site, cookie_done)
    if _gate_detected(page, portal):
        return "stopped", []
    _wait_for_cards(page, portal.card_selectors)
    human_scroll(page)
    page.wait_for_timeout(1000)
    items = page.evaluate(portal.cards_js)
    jobs = [job for job in (portal.make_job(item) for item in items) if job is not None]
    if jobs:
        return "found", jobs
    if _page_says_no_results(page):
        return "no_results", []
    return "unreadable", []


def _open_page(page: Page, portal: _Portal, term: str) -> bool:
    try:
        page.goto(portal.url_for_term(term), wait_until="domcontentloaded", timeout=settings.PAGE_TIMEOUT_MS)
        page.wait_for_timeout(2000)
        return True
    except Exception as error:
        print(f"  [{portal.site}] Navigation failed ({type(error).__name__}) - skip this term")
        run_report.set_status(portal.site, "ok_partial", "a search page could not be opened")
        return False


def _dismiss_cookies_once(page: Page, site: str, cookie_done: list[bool]) -> None:
    if cookie_done[0]:
        return
    dismiss_cookies(page, site)
    page.wait_for_timeout(1500)
    cookie_done[0] = True


def _gate_detected(page: Page, portal: _Portal) -> bool:
    """A block or login wall ends the scan of this portal; it is reported, never bypassed."""
    block_reason = detect_block(page)
    if block_reason or portal.is_blocked(page):
        reason = block_reason or "login wall"
        screenshot = debug_artifacts(page, f"{portal.site.replace('.', '_')}_gate")
        run_report.set_status(portal.site, "blocked", reason, final_url=page.url, screenshot=screenshot)
        print(f"  [{portal.site}] Block detected ({reason}) - stop")
        return True
    auth_reason = detect_auth_gate(page)
    if auth_reason:
        run_report.set_status(portal.site, "requires_auth", auth_reason, final_url=page.url)
        return True
    return False


def _wait_for_cards(page: Page, selectors: tuple[str, ...]) -> None:
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=5000)
            return
        except Exception:
            pass


def _page_says_no_results(page: Page) -> bool:
    try:
        text = page.evaluate("() => document.body ? document.body.innerText : ''").lower()
    except Exception:
        return False
    return any(marker in text for marker in _NO_RESULTS_MARKERS)


def _report_outcome(site: str, jobs: list[dict], outcomes: list[str]) -> None:
    """Set an explicit status when no listing was read; gates already set theirs."""
    if jobs:
        return
    if any(outcome in ("stopped", "navigation_failed") for outcome in outcomes):
        return
    if outcomes and all(outcome == "no_results" for outcome in outcomes):
        run_report.set_status(site, "no_results", "the portal reports no listings for these searches")
        return
    run_report.set_status(site, "selector_broken", "pages loaded but no listing cards were found")


# ---------------------------------------------------------------- the two scrapers

def _indeed_portal() -> _Portal:
    return _Portal(
        site=INDEED_SITE,
        url_for_term=lambda term: indeed_search_url(term, settings.SEARCH_PLACE, settings.SEARCH_RADIUS_KM),
        cards_js=_INDEED_CARDS_JS,
        card_selectors=_INDEED_CARD_SELECTORS,
        make_job=build_indeed_job,
        is_blocked=lambda _page: False,
    )


def _linkedin_portal() -> _Portal:
    return _Portal(
        site=LINKEDIN_SITE,
        url_for_term=lambda term: linkedin_search_url(term, settings.SEARCH_PLACE, settings.SEARCH_RADIUS_KM),
        cards_js=LINKEDIN_CARDS_JS,
        card_selectors=_LINKEDIN_CARD_SELECTORS,
        make_job=build_linkedin_job,
        is_blocked=linkedin_is_blocked,
    )


def _run_portal(context: BrowserContext, portal: _Portal) -> list[dict]:
    page = new_stealth_page(context)
    try:
        return _search_all_terms(page, portal)
    finally:
        try:
            page.close()
        except Exception:
            pass


@retry()
def scrape_indeed_it(context: BrowserContext) -> list[dict]:
    return _run_portal(context, _indeed_portal())


@retry()
def scrape_linkedin_it(context: BrowserContext) -> list[dict]:
    return _run_portal(context, _linkedin_portal())

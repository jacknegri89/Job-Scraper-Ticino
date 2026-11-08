"""Dry run: quickly check every portal (reachable, not blocked, result selector present).

It opens one page per site and reads nothing else, so it takes minutes, not an hour.
Add a portal here with its entry page and a selector that only exists when results are shown.
"""

import time
from typing import Any

from playwright.sync_api import sync_playwright

from scrapers import create_browser_context
from scrapers import settings as config
from scrapers.frontaliereticino_ch import _download_index as download_frontaliereticino_index
from scrapers.page_guard import detect_auth_gate, detect_block, dismiss_cookies
from scrapers.site_report import classify_exception, run_report

ProbeEntry = tuple[str, str]


def _close_quietly(obj: Any) -> None:
    try:
        obj.close()
    except Exception:
        pass

PROBES: dict[str, ProbeEntry] = {
    "jobs.ch": ("https://www.jobs.ch/en/vacancies/?term=operaio&location=ticino",
                'a[data-cy="job-link"]'),
    "carriera.ch": ("https://www.carriera.ch/offerte/annunci-offerte-lavoro_0_0_0.html",
                    "tr td a"),
    "gigroup.ch": ("https://ch.gigroup.com/it/posizioni-aperte/?npage=1",
                   ".ggp-job-item"),
    "randstad.ch": ("https://www.randstad.ch/it/lavoro/re-ticino/",
                    'a[href*="/it/lavoro/"]'),
    "orienta.ch": ("https://www.orienta.ch/it/orienta-job/offerte-di-lavoro.html?page=1",
                   "article a[href*='/offerta-di-lavoro/']"),
    "jobscout24.ch": ("https://www.jobscout24.ch/de/jobs/ticino/?p=1",
                      'a[href^="/de/job/"]'),
    "indeed.ch": ("https://ch.indeed.com/jobs?q=&l=Ticino&radius=50", "a[data-jk]"),
    "adecco.ch": ("https://www.adecco.com/it-ch/trovare-lavoro?jobsearch-title=&location=Ticino",
                  "article[class*='JobSearch_job-search-card']"),
    "manpower.ch": ("https://www.manpower.ch/it/trova-lavoro/citta/lugano",
                    'a[href*="/it/job/"]'),
    "linkedin.ch": ("https://www.linkedin.com/jobs/search/?keywords=&location=Ticino%2C+Switzerland",
                    '[class*="base-card"]'),
    "indeed.it": ("https://it.indeed.com/jobs?q=sviluppatore&l=Lombardia", "a[data-jk]"),
    "linkedin.it": ("https://www.linkedin.com/jobs/search/?keywords=sviluppatore&location=Lombardia%2C+Italia",
                    '[class*="base-card"]'),
}


def _probe_frontaliereticino(started_at: float) -> None:
    site = "frontaliereticino.ch"
    try:
        count = _load_frontaliereticino_count()
        run_report.finish(site, 0, time.perf_counter() - started_at,
                          status="ok", reason=f"JSON index ok ({count} records)")
        print(f"  [{site}] ok - JSON index with {count} records")
    except Exception as exc:
        status, reason = classify_exception(exc)
        run_report.finish(site, 0, time.perf_counter() - started_at,
                          status=status, reason=reason)
        print(f"  [{site}] {status} - {reason}")


def _load_frontaliereticino_count() -> int:
    return len(download_frontaliereticino_index())


def _probe_check_selector(page: Any, site: str, ready_selector: str, started_at: float) -> None:
    from scrapers.site_report import debug_artifacts

    try:
        page.wait_for_selector(ready_selector, timeout=10_000, state="attached")
        run_report.finish(site, 0, time.perf_counter() - started_at,
                          status="ok", reason="result selector is present")
        print(f"  [{site}] ok")
    except Exception:
        screenshot = debug_artifacts(page, f"probe_{site.replace('.', '_')}")
        run_report.set_status(site, "selector_broken",
                              f"selector {ready_selector!r} not found",
                              final_url=page.url, screenshot=screenshot)
        run_report.finish(site, 0, time.perf_counter() - started_at)


def _probe_browser_site(context: Any, site: str, url: str, ready_selector: str, started_at: float) -> None:
    from scrapers import new_stealth_page

    print(f"  [{site}] {url[:70]}...")
    page = new_stealth_page(context)
    try:
        _open_probe_page(page, site, url)
        _handle_probe_result(page, site, ready_selector, started_at)
    except Exception as exc:
        _finish_probe_error(site, exc, started_at)
    finally:
        _close_quietly(page)


def _open_probe_page(page: Any, site: str, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=config.PAGE_TIMEOUT_MS)
    page.wait_for_timeout(1500)
    dismiss_cookies(page, site)


def _handle_probe_result(page: Any, site: str, ready_selector: str, started_at: float) -> None:
    block_reason = detect_block(page)
    auth_reason = detect_auth_gate(page)
    if block_reason:
        _set_probe_status(page, site, "blocked", block_reason, started_at)
    elif auth_reason:
        _set_probe_status(page, site, "requires_auth", auth_reason, started_at)
    else:
        _probe_check_selector(page, site, ready_selector, started_at)


def _set_probe_status(page: Any, site: str, status: str, reason: str, started_at: float) -> None:
    from scrapers.site_report import debug_artifacts

    screenshot = debug_artifacts(page, f"probe_{site.replace('.', '_')}")
    run_report.set_status(site, status, reason, final_url=page.url, screenshot=screenshot)
    run_report.finish(site, 0, time.perf_counter() - started_at)


def _finish_probe_error(site: str, exc: Exception, started_at: float) -> None:
    status, reason = classify_exception(exc)
    run_report.finish(site, 0, time.perf_counter() - started_at,
                      status=status, reason=reason)
    print(f"  [{site}] {status} - {reason}")


def run_dry_run(sites: list[str]) -> None:
    """Probe each site once and save the report."""
    print(f"[DRY-RUN] Probing {len(sites)} sites with {config.PAGE_TIMEOUT_MS} ms timeout.\n")
    with sync_playwright() as playwright:
        browser, context = create_browser_context(playwright)
        try:
            _run_probes(context, sites)
        finally:
            _close_quietly(browser)
    run_report.print_table()
    run_report.save()


def _run_probes(context: Any, sites: list[str]) -> None:
    for site in sites:
        started_at = time.perf_counter()
        if site == "monster.ch":
            _mark_monster_disabled(site, started_at)
        elif site == "frontaliereticino.ch":
            _probe_frontaliereticino(started_at)
        elif site in PROBES:
            url, ready_selector = PROBES[site]
            _probe_browser_site(context, site, url, ready_selector, started_at)
        else:
            run_report.finish(site, 0, 0, status="error", reason="no probe configured")


def _mark_monster_disabled(site: str, started_at: float) -> None:
    reason = "portal redirects to monster.com/de and is disabled"
    run_report.set_status(site, "disabled", reason)
    run_report.finish(site, 0, time.perf_counter() - started_at,
                      status="disabled", reason=reason)

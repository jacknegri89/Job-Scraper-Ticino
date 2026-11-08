"""Command-line entry point for JobScraper."""

import argparse
import json
import os
import sys
import time
import webbrowser
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

import ai_analyzer
import cache_store
import dashboard_builder
import distance_calculator
import fx_rates
import job_filter
import startup_config
import setup_panel
from ai_analyzer import AI_SUITABLE, analyze_jobs
from dashboard_builder import generate_html
from job_lifecycle import apply_verification, jobs_to_verify, merge_scan
from job_pipeline import PipelineResult, exclusion_reason, process_jobs
from job_status import STATUS_ACTIVE
from preferences import SearchPreferences, preferences_from_settings
from scrapers import check_listing, create_browser_context, fetch_description, save_session
from scrapers import settings as config
from scrapers.adecco_ch import scrape_adecco_ch
from scrapers.carriera_ch import scrape_carriera_ch
from scrapers.frontaliereticino_ch import scrape_frontaliereticino_ch
from scrapers.gigroup_ch import scrape_gigroup_ch
from scrapers.indeed_ch import scrape_indeed_ch
from scrapers.jobs_ch import scrape_jobs_ch
from scrapers.jobscout24_ch import scrape_jobscout24_ch
from scrapers.italy_portals import scrape_indeed_it, scrape_linkedin_it
from scrapers.linkedin_ch import scrape_linkedin_ch
from scrapers.manpower_ch import scrape_manpower_ch
from scrapers.monster_ch import scrape_monster_ch
from scrapers.orienta_ch import scrape_orienta_ch
from scrapers.page_guard import detect_auth_gate, detect_block, dismiss_cookies
from scrapers.randstad_ch import scrape_randstad_ch
from scrapers.site_report import ScrapeError, classify_exception, run_report

CACHE_FILE = Path("jobs_cache.json")

# A listing page takes about 7 seconds to open; the rest are read on the next run.
MAX_DESCRIPTIONS_PER_RUN = 60

# Set by _apply_search_settings when a saved panel configuration is used.
_AI_ENABLED = True
_ACTIVE_SOURCES: set[str] | None = None
_PREFERENCES = SearchPreferences()
_FX_MODE = fx_rates.FX_MODE_ECB
_FX_MANUAL_RATE: float | None = None

ScraperEntry = tuple[str, str, Callable[[Any], list[dict]]]
ProbeEntry = tuple[str, str]

SCRAPERS: list[ScraperEntry] = [
    ("JOBS.CH", "jobs.ch", scrape_jobs_ch),
    ("CARRIERA.CH", "carriera.ch", scrape_carriera_ch),
    ("GI GROUP CH", "gigroup.ch", scrape_gigroup_ch),
    ("RANDSTAD CH", "randstad.ch", scrape_randstad_ch),
    ("ORIENTA CH", "orienta.ch", scrape_orienta_ch),
    ("JOBSCOUT24 CH", "jobscout24.ch", scrape_jobscout24_ch),
    ("INDEED CH", "indeed.ch", scrape_indeed_ch),
    ("MONSTER CH", "monster.ch", scrape_monster_ch),
    ("ADECCO CH", "adecco.ch", scrape_adecco_ch),
    ("MANPOWER CH", "manpower.ch", scrape_manpower_ch),
    ("FRONTALIERETICINO CH", "frontaliereticino.ch", scrape_frontaliereticino_ch),
    ("LINKEDIN CH", "linkedin.ch", scrape_linkedin_ch),
    ("INDEED IT", "indeed.it", scrape_indeed_it),
    ("LINKEDIN IT", "linkedin.it", scrape_linkedin_it),
]

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


def _configure_console() -> None:
    """Keep Windows terminals alive when a portal returns unusual text."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


def _format_seconds(seconds: float) -> str:
    seconds_int = int(seconds)
    if seconds_int < 60:
        return f"{seconds_int}s"
    minutes, remaining = divmod(seconds_int, 60)
    if minutes < 60:
        return f"{minutes}m {remaining:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _progress_bar(done: int, total: int) -> str:
    width = 38
    percent = done / total if total else 0
    filled = int(width * percent)
    return "#" * filled + "-" * (width - filled)


def _estimate_eta(done: int, total: int, step_times: list[float]) -> str:
    if done >= total:
        return "complete"
    if not step_times:
        return "..."
    average = sum(step_times) / len(step_times)
    return f"~{_format_seconds(average * (total - done))}"


def _print_progress(done: int, total: int, elapsed: float, step_times: list[float], phase: str = "Sites", label: str = "") -> None:
    print(f"\n{'-' * 64}")
    print(_progress_message(done, total, elapsed, step_times, phase, label))
    print(f"{'-' * 64}\n")


def _progress_message(done: int, total: int, elapsed: float, step_times: list[float], phase: str, label: str) -> str:
    percent = done / total if total else 0
    label_text = f"  >> {label}" if label else ""
    return (
        f"  {phase}: [{_progress_bar(done, total)}] {int(percent * 100):3d}% "
        f"({done}/{total})  {_format_seconds(elapsed)} elapsed  "
        f"ETA {_estimate_eta(done, total, step_times)}{label_text}"
    )


def _context_alive(context: Any) -> bool:
    try:
        _ = context.pages
        return True
    except Exception:
        return False


def _revive_context(playwright: Any, browser: Any, context: Any) -> tuple[Any, Any]:
    print("[WARN] Browser context closed. Creating a new one.")
    _close_quietly(browser)
    return create_browser_context(playwright)


def _close_quietly(obj: Any) -> None:
    try:
        obj.close()
    except Exception:
        pass


def _save_cache(jobs: list[dict]) -> None:
    cache_store.save_jobs(CACHE_FILE, jobs)
    print(f"[CACHE] Saved {len(jobs)} jobs to {CACHE_FILE}")


def _load_cache() -> list[dict]:
    if not CACHE_FILE.exists():
        print("[ERROR] No jobs_cache.json found. Run: python main.py")
        sys.exit(1)
    jobs = cache_store.load_jobs(CACHE_FILE)
    saved_at = datetime.fromtimestamp(CACHE_FILE.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    print(f"[CACHE] Loaded {len(jobs)} jobs from {CACHE_FILE} saved at {saved_at}")
    return jobs


def _read_previous_jobs() -> list[dict]:
    """Jobs from earlier scans; an unreadable cache stops the run instead of being overwritten."""
    return cache_store.load_jobs(CACHE_FILE)


def _current_fx_rate() -> fx_rates.FxRate:
    return fx_rates.get_fx_rate(_FX_MODE, _FX_MANUAL_RATE)


def _select_scrapers(only: str) -> list[ScraperEntry]:
    if not only:
        return SCRAPERS
    wanted = [item.strip().lower() for item in only.split(",") if item.strip()]
    if not wanted:
        _exit_unknown_site(only)
    available_sites = [site for _, site, _ in SCRAPERS]
    for requested_site in wanted:
        if not any(requested_site in site for site in available_sites):
            _exit_unknown_site(only)
    selected = [entry for entry in SCRAPERS if _matches_site(entry[1], wanted)]
    if not selected:
        _exit_unknown_site(only)
    return selected


def _matches_site(site: str, wanted: list[str]) -> bool:
    return any(item in site for item in wanted)


def _exit_unknown_site(only: str) -> None:
    print(f"[ERROR] --only {only!r} does not match any supported site.")
    print("Available sites:", ", ".join(site for _, site, _ in SCRAPERS))
    sys.exit(1)


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
    import urllib.request

    request = urllib.request.Request(
        "https://cdn.frontaliereticino.ch/data/jobs-it-index.json",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return len(json.loads(response.read().decode("utf-8")))


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


def _dry_run(only: str = "") -> None:
    selected = _select_scrapers(only)
    print(f"[DRY-RUN] Probing {len(selected)} sites with {config.PAGE_TIMEOUT_MS} ms timeout.\n")
    with sync_playwright() as playwright:
        browser, context = create_browser_context(playwright)
        try:
            _run_probes(context, selected)
        finally:
            _close_quietly(browser)
    run_report.print_table()
    run_report.save()


def _run_probes(context: Any, selected: list[ScraperEntry]) -> None:
    for _label, site, _scraper in selected:
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


def _scrape_one_site(scraper: Callable[[Any], list[dict]], site: str, context: Any) -> list[dict]:
    started_at = time.perf_counter()
    try:
        jobs = scraper(context)
    except ScrapeError as exc:
        run_report.finish(site, 0, time.perf_counter() - started_at,
                          status=exc.status, reason=exc.reason, attempts=exc.attempts)
        return []
    except Exception as exc:
        status, reason = classify_exception(exc)
        run_report.finish(site, 0, time.perf_counter() - started_at,
                          status=status, reason=reason)
        return []
    run_report.finish(site, len(jobs), time.perf_counter() - started_at)
    return jobs


def _print_scan_summary(result: PipelineResult) -> None:
    for source, stats in sorted(result.stats.items()):
        run_report.add_job_stats(source, stats.collected, stats.valid, stats.duplicates, dict(stats.excluded))
        reasons = ", ".join(f"{reason}:{count}" for reason, count in sorted(stats.excluded.items()))
        reason_text = ""
        if reasons:
            reason_text = f" ({reasons})"
        print(f"[FILTER] {source}: collected {stats.collected}, valid {stats.valid}, "
              f"duplicates {stats.duplicates}, excluded {sum(stats.excluded.values())}{reason_text}")


def _download_descriptions(context: Any, valid_jobs: list[dict]) -> None:
    jobs_to_download = [job for job in valid_jobs if _needs_description(job)]
    if not jobs_to_download:
        return
    left_for_next_run = len(jobs_to_download) - MAX_DESCRIPTIONS_PER_RUN
    if left_for_next_run > 0:
        print(f"[DESC] Opening the {MAX_DESCRIPTIONS_PER_RUN} newest pages now; {left_for_next_run} more on the next run.")
    _download_description_batch(context, jobs_to_download[:MAX_DESCRIPTIONS_PER_RUN], len(valid_jobs))


def _needs_description(job: dict) -> bool:
    """Only listings seen in this scan are opened; cached ones may be gone or blocked."""
    if job.get("description"):
        return False
    return job.get("status") in (None, STATUS_ACTIVE)


def _download_description_batch(context: Any, jobs_to_download: list[dict], total_valid: int) -> None:
    started_at = time.perf_counter()
    step_times: list[float] = []
    cached_count = total_valid - len(jobs_to_download)
    print(f"\n=== DESCRIPTIONS ({len(jobs_to_download)} to download now, {cached_count} other jobs of {total_valid}) ===")
    for index, job in enumerate(jobs_to_download):
        _download_one_description(context, job, index, jobs_to_download, started_at, step_times)
    _print_progress(len(jobs_to_download), len(jobs_to_download),
                    time.perf_counter() - started_at, step_times, phase="Descriptions")


def _download_one_description(context: Any, job: dict, index: int, jobs_to_download: list[dict], started_at: float, step_times: list[float]) -> None:
    _print_progress(index, len(jobs_to_download), time.perf_counter() - started_at,
                    step_times, phase="Descriptions", label=job.get("title", "")[:40])
    step_started_at = time.perf_counter()
    details = fetch_description(context, job.get("url", ""))
    job["description"] = details["description"]
    job["email"] = details["email"]
    step_times.append(time.perf_counter() - step_started_at)
    email_label = " [email]" if details["email"] else ""
    print(f"[DESC] {index + 1}/{len(jobs_to_download)} - {job.get('title', '')[:50]}"
          f"{email_label} ({_format_seconds(step_times[-1])})")


def _run_scrape(only: str = "", scan_only: bool = False) -> list[dict] | None:
    selected = _select_scrapers(only)
    jobs, completed = _collect_jobs(selected, scan_only)
    return _finish_scrape_run(jobs, completed, scan_only)


def _collect_jobs(selected: list[ScraperEntry], scan_only: bool) -> tuple[list[dict], bool]:
    with sync_playwright() as playwright:
        return _collect_with_browser(playwright, selected, scan_only)


def _collect_with_browser(playwright: Any, selected: list[ScraperEntry], scan_only: bool) -> tuple[list[dict], bool]:
    raw_jobs: list[dict] = []
    jobs: list[dict] = []
    browser, context = create_browser_context(playwright)
    try:
        browser, context = _scrape_selected_sites(playwright, browser, context, selected, raw_jobs)
        jobs = _build_job_list(raw_jobs, scan_only)
        if not scan_only:
            _download_descriptions(context, jobs)
            _verify_possibly_expired(context, jobs)
        return jobs, True
    except KeyboardInterrupt:
        return jobs or _interrupted_jobs(raw_jobs), False
    except Exception as exc:
        return jobs or _critical_error_jobs(exc, raw_jobs), False
    finally:
        save_session(context)
        _close_quietly(browser)


def _build_job_list(raw_jobs: list[dict], scan_only: bool) -> list[dict]:
    """Filter the scan, then combine it with the cache so blocked portals lose nothing."""
    result = process_jobs(raw_jobs, _PREFERENCES)
    _print_scan_summary(result)
    if scan_only:
        return result.jobs
    outcomes = {site_result.site: site_result.status for site_result in run_report.results}
    jobs, status_counts = merge_scan(_read_previous_jobs(), result.jobs, outcomes, _PREFERENCES, datetime.now())
    summary = ", ".join(f"{status}:{count}" for status, count in sorted(status_counts.items()))
    print(f"[CACHE] {len(jobs)} jobs after merging with the cache ({summary}).")
    return jobs


def _verify_possibly_expired(context: Any, jobs: list[dict]) -> None:
    """Open a few possibly-expired listing pages to learn whether they are really gone."""
    candidates = jobs_to_verify(jobs, _PREFERENCES.verify_limit)
    if not candidates:
        return
    print(f"\n=== VERIFY ({len(candidates)} possibly expired listings) ===")
    verdict_counts: dict[str, int] = {}
    for job in candidates:
        verdict = check_listing(context, job.get("url", ""))
        apply_verification(job, verdict, datetime.now())
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
    print("[VERIFY] " + ", ".join(f"{verdict}:{count}" for verdict, count in sorted(verdict_counts.items())))


def _interrupted_jobs(raw_jobs: list[dict]) -> list[dict]:
    print("\n[STOP] Interrupted. Saving what was collected.")
    return process_jobs(raw_jobs, _PREFERENCES).jobs


def _critical_error_jobs(exc: Exception, raw_jobs: list[dict]) -> list[dict]:
    print(f"[CRITICAL ERROR] {exc}")
    return process_jobs(raw_jobs, _PREFERENCES).jobs


def _scrape_selected_sites(
    playwright: Any,
    browser: Any,
    context: Any,
    selected: list[ScraperEntry],
    raw_jobs: list[dict],
) -> tuple[Any, Any]:
    started_at = time.perf_counter()
    step_times: list[float] = []
    for index, (name, site, scraper) in enumerate(selected):
        browser, context = _ensure_context_alive(playwright, browser, context)
        raw_jobs.extend(_scrape_site_with_progress(scraper, site, name, index, selected, started_at, step_times, context))
    _print_progress(len(selected), len(selected), time.perf_counter() - started_at, step_times)
    return browser, context


def _ensure_context_alive(playwright: Any, browser: Any, context: Any) -> tuple[Any, Any]:
    if _context_alive(context):
        return browser, context
    return _revive_context(playwright, browser, context)


def _scrape_site_with_progress(scraper: Callable[[Any], list[dict]], site: str, name: str, index: int, selected: list[ScraperEntry], started_at: float, step_times: list[float], context: Any) -> list[dict]:
    _print_progress(index, len(selected), time.perf_counter() - started_at, step_times, label=name)
    print(f"=== {name} ===")
    step_started_at = time.perf_counter()
    jobs = _scrape_one_site(scraper, site, context)
    step_times.append(time.perf_counter() - step_started_at)
    print(f"  +- {len(jobs)} jobs in {_format_seconds(step_times[-1])}")
    return jobs


def _finish_scrape_run(jobs: list[dict], completed: bool, scan_only: bool = False) -> list[dict] | None:
    run_report.print_table()
    run_report.save()
    if not completed:
        if not scan_only:
            _save_completed_or_partial(jobs, False)
        return None
    if scan_only:
        return jobs
    _save_completed_or_partial(jobs, True)
    return jobs


def _save_completed_or_partial(jobs: list[dict], completed: bool) -> None:
    if jobs and completed:
        _save_cache(jobs)
    elif jobs:
        partial_file = Path("jobs_cache.partial.json")
        partial_file.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[CACHE] Incomplete scan saved to {partial_file}. Main cache was not overwritten.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JobScraper")
    _add_scan_args(parser)
    _add_runtime_args(parser)
    return parser.parse_args()


def _add_scan_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--reanalyze", action="store_true",
                        help="analyze pending cached jobs without scraping")
    parser.add_argument("--scan-only", action="store_true",
                        help="scan sites and write the report, but skip descriptions, AI, and HTML")
    parser.add_argument("--dry-run", action="store_true",
                        help="probe each site without a full scrape")
    parser.add_argument("--only", default="",
                        help="limit to matching sites, for example --only indeed,linkedin")


def _add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--panel", "--configure", action="store_true", dest="panel",
                        help="open the local configuration panel")
    parser.add_argument("--background", action="store_true",
                        help="run without opening the configuration panel")
    parser.add_argument("--project-dir", action="store_true",
                        help="write relative outputs in the project directory")
    parser.add_argument("--headless", action="store_true",
                        help="hide the browser window")
    parser.add_argument("--timeout", type=int, default=0, metavar="MS",
                        help=f"navigation timeout in ms, default {config.PAGE_TIMEOUT_MS}")
    parser.add_argument("--auth", default="", metavar="SITE",
                        help="manual login and saved session, for example --auth linkedin")


def _apply_cli_overrides(args: argparse.Namespace) -> None:
    if args.headless:
        config.HEADLESS = True
    if args.timeout > 0:
        config.PAGE_TIMEOUT_MS = args.timeout


def _run_auth_mode(site: str) -> None:
    from scrapers.session import run_auth_flow

    with sync_playwright() as playwright:
        ok = run_auth_flow(playwright, site.strip().lower())
    sys.exit(0 if ok else 1)


def _run_scan_mode(args: argparse.Namespace, started_at: datetime) -> list[dict] | None:
    if args.dry_run:
        print(f"[START] {started_at:%Y-%m-%d %H:%M} - dry-run")
        _dry_run(args.only)
        return None
    if args.reanalyze:
        print(f"[REANALYZE] {started_at:%Y-%m-%d %H:%M} - AI analysis from cache")
        return _load_cache()
    print(f"[START] {started_at:%Y-%m-%d %H:%M}" + (" - scan-only" if args.scan_only else ""))
    return _run_scrape(args.only, scan_only=args.scan_only)


def _finish_scan_only(args: argparse.Namespace, started_at: datetime) -> bool:
    if not args.scan_only:
        return False
    elapsed = int((datetime.now() - started_at).total_seconds())
    print(f"[DONE] Scan completed in {_format_seconds(elapsed)}. Report: scan_report.json")
    return True


def _finalize_jobs(valid_jobs: list[dict], started_at: datetime, retry_unanalyzable: bool = False) -> None:
    if _AI_ENABLED:
        analyzed_jobs = analyze_jobs(valid_jobs, retry_unanalyzable=retry_unanalyzable)
    else:
        print("[AI] Analysis is switched off in the settings.")
        analyzed_jobs = valid_jobs
    if analyzed_jobs:
        _save_cache(analyzed_jobs)
    if _AI_ENABLED and analyzed_jobs and not any(job.get(AI_SUITABLE) is not None for job in analyzed_jobs):
        print("[HINT] To analyze missing cached jobs: python main.py --reanalyze")
    generate_html(_visible_jobs(analyzed_jobs), fx_rate=_current_fx_rate())
    _open_dashboard(started_at)


def _visible_jobs(jobs: list[dict]) -> list[dict]:
    """Jobs that match the current settings. Everything else stays in the cache untouched."""
    visible_jobs = []
    for job in jobs:
        if not _from_active_source(job):
            continue
        if exclusion_reason(job, _PREFERENCES):
            continue
        visible_jobs.append(job)
    return visible_jobs


def _from_active_source(job: dict) -> bool:
    if _ACTIVE_SOURCES is None:
        return True
    job_sources = {reference.get("source") for reference in job.get("sources") or []}
    job_sources.add(job.get("source"))
    return bool(job_sources & _ACTIVE_SOURCES)


def _open_dashboard(started_at: datetime) -> None:
    elapsed = int((datetime.now() - started_at).total_seconds())
    print(f"[DONE] Completed in {_format_seconds(elapsed)}.")
    webbrowser.open(Path("index.html").resolve().as_uri())


def _initial_settings(available_sources: set[str]) -> dict:
    settings = startup_config.default_settings(sorted(available_sources), job_filter.SEARCH_TERMS)
    legacy_config = sys.modules.get("user_config")
    if legacy_config is not None:
        settings["home_city"] = distance_calculator.HOME_CITY
        settings["home_lat"] = distance_calculator.HOME_LAT
        settings["home_lng"] = distance_calculator.HOME_LNG
        settings["candidate_profile"] = ai_analyzer._profile_from_config(legacy_config)
    return settings


def _apply_search_settings(settings: dict, args: argparse.Namespace) -> None:
    global _AI_ENABLED, _ACTIVE_SOURCES, _PREFERENCES, _FX_MODE, _FX_MANUAL_RATE
    _PREFERENCES = preferences_from_settings(settings)
    job_filter.SEARCH_TERMS[:] = settings["search_terms"]
    distance_calculator._HOME_COORDINATES = None
    if settings["home_lat"] is not None:
        distance_calculator._HOME_COORDINATES = (settings["home_lat"], settings["home_lng"])
    dashboard_builder.HOME_CITY = settings["home_city"] or "Home"
    ai_analyzer.CANDIDATE_PROFILE_OVERRIDE = settings["candidate_profile"]
    _AI_ENABLED = settings["ai_enabled"]
    _FX_MODE = settings["fx_mode"]
    _FX_MANUAL_RATE = settings["fx_manual_eur_per_chf"]
    _ACTIVE_SOURCES = set(settings["sources"])
    if args.timeout <= 0:
        config.PAGE_TIMEOUT_MS = settings["timeout_ms"]
    config.MAX_ATTEMPTS = settings["attempts"]
    config.SEARCH_PLACE = settings["home_city"]
    config.SEARCH_RADIUS_KM = settings["radius_km"]
    if not args.only:
        args.only = ",".join(settings["sources"])
    else:
        requested_sources = [item.strip().lower() for item in args.only.split(",") if item.strip()]
        for _, site, _ in SCRAPERS:
            if _matches_site(site, requested_sources):
                _ACTIVE_SOURCES.add(site)
    if settings["headless"]:
        config.HEADLESS = True
    _warn_about_radius_without_home(settings)


def _warn_about_radius_without_home(settings: dict) -> None:
    if settings["radius_km"] is not None and settings["home_lat"] is None:
        print("[CONFIG] A distance limit is set but there is no starting point: the limit is ignored.")


def _setup_search(args: argparse.Namespace) -> bool:
    available_sources = {site for _, site, _ in SCRAPERS if site != "monster.ch"}
    settings = startup_config.load_settings(startup_config.SETTINGS_FILE, available_sources)
    open_panel = args.panel
    if not any((args.background, args.dry_run, args.scan_only, args.reanalyze,
                args.only, args.headless, args.project_dir)):
        open_panel = True
    if open_panel:
        settings = settings or _initial_settings(available_sources)
        setup_panel.open_panel(settings, available_sources)
        return False
    if settings is not None:
        _apply_search_settings(settings, args)
    elif not args.dry_run:
        print("[CONFIG] No saved settings: using user_config.py or the built-in defaults.")
    return True


def main() -> None:
    _configure_console()
    args = _parse_args()
    if args.project_dir:
        os.chdir(Path(__file__).resolve().parent)
    started_at = datetime.now()
    _apply_cli_overrides(args)
    if args.auth:
        _run_auth_mode(args.auth)
    try:
        if not _setup_search(args):
            return
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"[CONFIG] Error: {error}")
        sys.exit(1)
    valid_jobs = _run_scan_mode(args, started_at)
    if valid_jobs is None:
        if args.background:
            sys.exit(1)
        return
    if _finish_scan_only(args, started_at):
        return
    _finalize_jobs(valid_jobs, started_at, retry_unanalyzable=args.reanalyze)


if __name__ == "__main__":
    main()

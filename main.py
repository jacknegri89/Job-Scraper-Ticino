"""Command-line entry point for the Ticino job scraper."""

import argparse
import json
import sys
import time
import webbrowser
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from ai_analyzer import AI_DESCRIPTION, AI_GROSS_SALARY, AI_REASON, AI_SUITABLE, analyze_jobs, normalize_ai_fields
from dashboard_builder import generate_html
from job_filter import filter_jobs, is_valid_job, normalize_url
from scrapers import SESSION_FILE, create_browser_context, fetch_description, save_session
from scrapers import settings as config
from scrapers.adecco_ch import scrape_adecco_ch
from scrapers.carriera_ch import scrape_carriera_ch
from scrapers.frontaliereticino_ch import scrape_frontaliereticino_ch
from scrapers.gigroup_ch import scrape_gigroup_ch
from scrapers.indeed_ch import scrape_indeed_ch
from scrapers.jobs_ch import scrape_jobs_ch
from scrapers.jobscout24_ch import scrape_jobscout24_ch
from scrapers.linkedin_ch import scrape_linkedin_ch
from scrapers.manpower_ch import scrape_manpower_ch
from scrapers.monster_ch import scrape_monster_ch
from scrapers.orienta_ch import scrape_orienta_ch
from scrapers.page_guard import detect_auth_gate, detect_block, dismiss_cookies
from scrapers.randstad_ch import scrape_randstad_ch
from scrapers.site_report import ScrapeError, classify_exception, run_report

CACHE_FILE = Path("jobs_cache.json")

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
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
    _close_quietly(browser)
    return create_browser_context(playwright)


def _close_quietly(obj: Any) -> None:
    try:
        obj.close()
    except Exception:
        pass


def _save_cache(jobs: list[dict]) -> None:
    jobs = [normalize_ai_fields(job) for job in jobs]
    CACHE_FILE.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[CACHE] Saved {len(jobs)} jobs to {CACHE_FILE}")


def _load_cache() -> list[dict]:
    if not CACHE_FILE.exists():
        print("[ERROR] No jobs_cache.json found. Run: python main.py")
        sys.exit(1)
    jobs = [normalize_ai_fields(job) for job in json.loads(CACHE_FILE.read_text(encoding="utf-8"))]
    saved_at = datetime.fromtimestamp(CACHE_FILE.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    print(f"[CACHE] Loaded {len(jobs)} jobs from {CACHE_FILE} saved at {saved_at}")
    return jobs


def _merge_with_cache(new_jobs: list[dict], scanned_sources: set[str]) -> list[dict]:
    if not CACHE_FILE.exists():
        return new_jobs
    old_jobs = _read_cache_or_empty()
    kept_jobs = [job for job in old_jobs if job.get("source") not in scanned_sources]
    if kept_jobs:
        print(f"[CACHE] Preserved {len(kept_jobs)} jobs from sources not scanned.")
    return kept_jobs + new_jobs


def _read_cache_or_empty() -> list[dict]:
    try:
        return [normalize_ai_fields(job) for job in json.loads(CACHE_FILE.read_text(encoding="utf-8"))]
    except Exception:
        return []


def _reuse_previous_data(valid_jobs: list[dict]) -> int:
    old_jobs_by_url = _old_jobs_by_url()
    reused_count = 0
    for job in valid_jobs:
        old_job = old_jobs_by_url.get(normalize_url(job.get("url", "")))
        if old_job:
            reused_count += _reuse_one_job(job, old_job)
    return reused_count


def _old_jobs_by_url() -> dict[str, dict]:
    old_jobs = _read_cache_or_empty()
    return {
        normalize_url(job.get("url", "")): job
        for job in old_jobs
        if normalize_url(job.get("url", ""))
    }


def _reuse_one_job(job: dict, old_job: dict) -> int:
    if old_job.get("description") and not job.get("description"):
        job["description"] = old_job["description"]
        job["email"] = old_job.get("email", "")
    old_job = normalize_ai_fields(old_job)
    if old_job.get(AI_SUITABLE) is not None:
        _copy_ai_fields(job, old_job)
    return 1


def _copy_ai_fields(job: dict, old_job: dict) -> None:
    job[AI_SUITABLE] = old_job[AI_SUITABLE]
    job[AI_REASON] = old_job.get(AI_REASON, "")
    job[AI_DESCRIPTION] = old_job.get(AI_DESCRIPTION, "")
    job[AI_GROSS_SALARY] = old_job.get(AI_GROSS_SALARY)


def _select_scrapers(only: str) -> list[ScraperEntry]:
    if not only:
        return SCRAPERS
    wanted = [item.strip().lower() for item in only.split(",") if item.strip()]
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
    import urllib.request

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


def _print_filter_summary(raw_jobs: list[dict], valid_jobs: list[dict]) -> None:
    in_area = sum(1 for job in raw_jobs if is_valid_job(job))
    print(f"[FILTER] {len(raw_jobs)} raw -> {in_area} in allowed cities -> {len(valid_jobs)} unique")
    by_source = Counter(job.get("source", "?") for job in valid_jobs)
    print("[FILTER] By source: " + " | ".join(f"{site}:{count}" for site, count in sorted(by_source.items())))


def _download_descriptions(context: Any, valid_jobs: list[dict]) -> None:
    jobs_to_download = [job for job in valid_jobs if not job.get("description")]
    if not jobs_to_download:
        return
    _download_description_batch(context, jobs_to_download, len(valid_jobs))


def _download_description_batch(context: Any, jobs_to_download: list[dict], total_valid: int) -> None:
    started_at = time.perf_counter()
    step_times: list[float] = []
    cached_count = total_valid - len(jobs_to_download)
    print(f"\n=== DESCRIPTIONS ({len(jobs_to_download)} to download, {cached_count} cached) ===")
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


def _run_scrape(only: str = "", scan_only: bool = False) -> list[dict]:
    selected = _select_scrapers(only)
    valid_jobs, completed = _collect_valid_jobs(selected, scan_only)
    return _finish_scrape_run(valid_jobs, selected, only, completed)


def _collect_valid_jobs(selected: list[ScraperEntry], scan_only: bool) -> tuple[list[dict], bool]:
    with sync_playwright() as playwright:
        return _collect_with_browser(playwright, selected, scan_only)


def _collect_with_browser(playwright: Any, selected: list[ScraperEntry], scan_only: bool) -> tuple[list[dict], bool]:
    raw_jobs: list[dict] = []
    valid_jobs: list[dict] = []
    browser, context = create_browser_context(playwright)
    try:
        raw_jobs, browser, context = _scrape_selected_sites(playwright, browser, context, selected)
        valid_jobs = _prepare_valid_jobs(raw_jobs, context, scan_only)
        return valid_jobs, True
    except KeyboardInterrupt:
        return _interrupted_jobs(raw_jobs, valid_jobs), False
    except Exception as exc:
        return _critical_error_jobs(exc, raw_jobs, valid_jobs), False
    finally:
        save_session(context)
        _close_quietly(browser)


def _interrupted_jobs(raw_jobs: list[dict], valid_jobs: list[dict]) -> list[dict]:
    print("\n[STOP] Interrupted. Saving what was collected.")
    return valid_jobs or filter_jobs(raw_jobs)


def _critical_error_jobs(exc: Exception, raw_jobs: list[dict], valid_jobs: list[dict]) -> list[dict]:
    print(f"[CRITICAL ERROR] {exc}")
    return valid_jobs or filter_jobs(raw_jobs)


def _scrape_selected_sites(
    playwright: Any,
    browser: Any,
    context: Any,
    selected: list[ScraperEntry],
) -> tuple[list[dict], Any, Any]:
    raw_jobs: list[dict] = []
    started_at = time.perf_counter()
    step_times: list[float] = []
    for index, (name, site, scraper) in enumerate(selected):
        browser, context = _ensure_context_alive(playwright, browser, context)
        raw_jobs.extend(_scrape_site_with_progress(scraper, site, name, index, selected, started_at, step_times, context))
    _print_progress(len(selected), len(selected), time.perf_counter() - started_at, step_times)
    return raw_jobs, browser, context


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


def _prepare_valid_jobs(raw_jobs: list[dict], context: Any, scan_only: bool) -> list[dict]:
    valid_jobs = filter_jobs(raw_jobs)
    _print_filter_summary(raw_jobs, valid_jobs)
    reused_count = _reuse_previous_data(valid_jobs)
    if reused_count:
        print(f"[CACHE] Reused paid description/AI data for {reused_count} jobs.")
    if not scan_only:
        _download_descriptions(context, valid_jobs)
    return valid_jobs


def _finish_scrape_run(
    valid_jobs: list[dict],
    selected: list[ScraperEntry],
    only: str,
    completed: bool,
) -> list[dict]:
    run_report.print_table()
    run_report.save()
    if only:
        valid_jobs = _merge_with_cache(valid_jobs, {site for _, site, _ in selected})
    _save_completed_or_partial(valid_jobs, completed)
    return valid_jobs


def _save_completed_or_partial(valid_jobs: list[dict], completed: bool) -> None:
    if valid_jobs and completed:
        _save_cache(valid_jobs)
    elif valid_jobs:
        partial_file = Path("jobs_cache.partial.json")
        partial_file.write_text(json.dumps(valid_jobs, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[CACHE] Incomplete scan saved to {partial_file}. Main cache was not overwritten.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ticino job scraper")
    _add_scan_args(parser)
    _add_runtime_args(parser)
    return parser.parse_args()


def _add_scan_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--reanalyze", action="store_true",
                        help="rerun AI analysis from cache without scraping")
    parser.add_argument("--scan-only", action="store_true",
                        help="scan sites and write the report, but skip descriptions, AI, and HTML")
    parser.add_argument("--dry-run", action="store_true",
                        help="probe each site without a full scrape")
    parser.add_argument("--only", default="",
                        help="limit to matching sites, for example --only indeed,linkedin")


def _add_runtime_args(parser: argparse.ArgumentParser) -> None:
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


def _finalize_jobs(valid_jobs: list[dict], started_at: datetime) -> None:
    analyzed_jobs = analyze_jobs(valid_jobs)
    if analyzed_jobs:
        _save_cache(analyzed_jobs)
    if analyzed_jobs and not any(job.get(AI_SUITABLE) is not None for job in analyzed_jobs):
        print("[HINT] To rerun only AI analysis: python main.py --reanalyze")
    generate_html(analyzed_jobs)
    _open_dashboard(started_at)


def _open_dashboard(started_at: datetime) -> None:
    elapsed = int((datetime.now() - started_at).total_seconds())
    print(f"[DONE] Completed in {_format_seconds(elapsed)}.")
    webbrowser.open(Path("index.html").resolve().as_uri())


def main() -> None:
    _configure_console()
    args = _parse_args()
    started_at = datetime.now()
    _apply_cli_overrides(args)
    if args.auth:
        _run_auth_mode(args.auth)
    valid_jobs = _run_scan_mode(args, started_at)
    if valid_jobs is None or _finish_scan_only(args, started_at):
        return
    _finalize_jobs(valid_jobs, started_at)


if __name__ == "__main__":
    main()

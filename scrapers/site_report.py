# Structured scan report: one status per site.
#
# Possible statuses:
#   ok                    jobs collected, no issue
#   ok_partial            jobs collected, but part of the site is inaccessible
#   no_results            the site answered and says there are no matching listings
#   empty                 no jobs read and no proof that the page was understood
#                         (could be a real empty search or a changed page)
#   requires_auth         content behind login
#   requires_manual_login manual session needed: python main.py --auth <site>
#   blocked               captcha / anti-bot
#   timeout               page did not respond in time
#   network_error         DNS / connection / abort
#   browser_closed        browser or page closed during scraping
#   selector_broken       page reached but DOM structure not recognized
#   disabled              scraper intentionally disabled, for example monster.ch
#   error                 unclassified error; see reason

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page

from scrapers.settings import DEBUG_DIR, REPORT_FILE


@dataclass
class SiteResult:
    site:       str
    status:     str = "ok"
    jobs:       int = 0
    duration_s: float = 0.0
    attempts:   int = 1
    reason:     str = ""
    final_url:  str = ""
    screenshot: str = ""
    valid:      int = 0
    duplicates: int = 0
    excluded:   dict = field(default_factory=dict)


# Statuses that prove the site was read correctly.
READ_OK_STATUSES = ("ok", "no_results")
# Statuses where some data was read or the page was at least understood.
USABLE_STATUSES = ("ok", "ok_partial", "no_results")

OVERALL_SUCCESS = "success"
OVERALL_PARTIAL = "partial"
OVERALL_FAILURE = "failure"


class RunReport:
    """Collect results for all sites in one scan."""

    def __init__(self) -> None:
        self._results:   dict[str, SiteResult] = {}
        self._overrides: dict[str, dict]       = {}
        self.started = datetime.now()

    def set_status(self, site: str, status: str, reason: str = "",
                   final_url: str = "", screenshot: str = "") -> None:
        # Called by scrapers when they detect a gate (login, captcha) or a problem on
        # one page, without interrupting collection of jobs already found. A weaker
        # status never replaces a stronger one: a later "no_results" must not hide an
        # earlier failed page, and a later "ok_partial" must not hide a block.
        current = self._overrides.get(site)
        if current is not None and _issue_rank(current["status"]) > _issue_rank(status):
            print(f"  [report] {site}: {status} ignored, {current['status']} was already reported")
            return
        self._overrides[site] = {
            "status": status, "reason": reason,
            "final_url": final_url, "screenshot": screenshot,
        }
        print(f"  [report] {site}: {status}" + (f" - {reason}" if reason else ""))

    def finish(self, site: str, jobs: int, duration_s: float,
               status: str = "", reason: str = "", attempts: int = 1) -> SiteResult:
        status = _calculated_status(jobs, status)
        status, reason = _status_with_override(jobs, status, reason, self._overrides.get(site, {}))
        r = _site_result(site, jobs, duration_s, attempts, status, reason, self._overrides.get(site, {}))
        self._results[site] = r
        return r

    def add_job_stats(self, site: str, collected: int, valid: int, duplicates: int, excluded: dict) -> None:
        """Attach the filtering numbers of one site to its result."""
        result = self._results.get(site)
        if result is None:
            return
        result.jobs = collected
        result.valid = valid
        result.duplicates = duplicates
        result.excluded = dict(excluded)

    @property
    def results(self) -> list[SiteResult]:
        return list(self._results.values())

    def overall_status(self) -> str:
        """success: every site was read. partial: some were. failure: none was.

        A site that returned nothing without proof that its page was understood
        ("empty") never counts as read, so two portals answering is not a success.
        """
        return overall_status(self.results)

    def save(self, path: Path = REPORT_FILE) -> None:
        data = {
            "started":  self.started.isoformat(timespec="seconds"),
            "finished": datetime.now().isoformat(timespec="seconds"),
            "overall":  self.overall_status(),
            "sites":    [asdict(r) for r in self.results],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[REPORT] Saved to {path}")

    def print_table(self) -> None:
        if not self._results:
            return
        width_site, width_status = 22, 16
        line = "=" * 92
        print("\n" + line)
        print(f"  {'SITE':<{width_site}}{'STATUS':<{width_status}}{'READ':>5}{'VALID':>7}{'DUPES':>7}{'OUT':>5}  {'TIME':>6}  NOTE")
        print("-" * 92)
        for r in self.results:
            note = r.reason[:32]
            excluded_total = sum(r.excluded.values())
            print(f"  {r.site:<{width_site}}{r.status:<{width_status}}{r.jobs:>5}{r.valid:>7}{r.duplicates:>7}"
                  f"{excluded_total:>5}  {r.duration_s:>5.0f}s  {note}")
        print(line)
        sites_read = sum(1 for r in self.results if r.status in USABLE_STATUSES)
        print(f"  Overall: {self.overall_status()} ({sites_read}/{len(self.results)} sites read)\n")


def overall_status(results: list[SiteResult]) -> str:
    """Explicit criteria for a whole scan."""
    countable = [r for r in results if r.status != "disabled"]
    if not countable:
        return OVERALL_FAILURE
    if all(r.status in READ_OK_STATUSES for r in countable):
        return OVERALL_SUCCESS
    if any(r.status in USABLE_STATUSES for r in countable):
        return OVERALL_PARTIAL
    return OVERALL_FAILURE


def _calculated_status(jobs: int, status: str) -> str:
    if status:
        return status
    return "ok" if jobs > 0 else "empty"


def _status_with_override(
    jobs: int,
    status: str,
    reason: str,
    override: dict,
) -> tuple[str, str]:
    if not override:
        return status, reason

    reported_status = status
    status = override["status"]
    reason = override["reason"] or reason
    if jobs > 0 and status in _GATE_STATUSES:
        return "ok_partial", _partial_reason(status, override["reason"])
    if jobs > 0 and status in ("no_results", "selector_broken", "empty"):
        # Listings were read, so the source is not empty; part of it was not understood.
        return "ok_partial", _partial_reason(status, override["reason"])
    if jobs == 0 and status == "ok_partial":
        # "Partial" needs something read. A page that failed with nothing collected is a failure,
        # and the more precise cause (timeout, network error...) is kept when the scraper gave one.
        failure_status = reported_status if reported_status in _FAILURE_STATUSES else "error"
        return failure_status, _partial_reason("no listing could be read", reason)
    return status, reason


def _partial_reason(status: str, reason: str) -> str:
    if reason:
        return f"{status}: {reason}"
    return status


_GATE_STATUSES = ("requires_auth", "requires_manual_login", "blocked")
_FAILURE_STATUSES = ("timeout", "network_error", "browser_closed", "selector_broken", "error", *_GATE_STATUSES)


def _issue_rank(status: str) -> int:
    """How serious a reported problem is: gates first, then partial reads, then the rest."""
    if status in _GATE_STATUSES:
        return 3
    if status == "ok_partial":
        return 2
    if status in ("no_results", "empty"):
        return 0
    return 1


def _site_result(
    site: str,
    jobs: int,
    duration_s: float,
    attempts: int,
    status: str,
    reason: str,
    override: dict,
) -> SiteResult:
    return SiteResult(
        site=site, status=status, jobs=jobs,
        duration_s=round(duration_s, 1), attempts=attempts, reason=reason,
        final_url=override.get("final_url", ""), screenshot=override.get("screenshot", ""),
    )


# Shared instance imported by scrapers to report gates and blocks.
run_report = RunReport()


def debug_artifacts(page: Page, tag: str) -> str:
    # Save a screenshot plus HTML in debug/ for diagnostics.
    # Return the screenshot path, or "" if screenshot capture fails.
    # Never raises: this is called on error paths.
    DEBUG_DIR.mkdir(exist_ok=True)
    shot = _save_screenshot(page, tag)
    _save_html(page, tag)
    if shot:
        print(f"  [debug] {tag}: screenshot + HTML saved in {DEBUG_DIR}\\")
    return shot


def _save_screenshot(page: Page, tag: str) -> str:
    shot = ""
    try:
        shot_path = DEBUG_DIR / f"{tag}.png"
        page.screenshot(path=str(shot_path))
        shot = str(shot_path)
    except Exception:
        pass
    return shot


def _save_html(page: Page, tag: str) -> None:
    try:
        (DEBUG_DIR / f"{tag}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass


def classify_exception(e: Exception) -> tuple[str, str]:
    """Map a Playwright/network exception to (status, reason)."""
    msg  = str(e)
    low  = msg.lower()
    name = type(e).__name__.lower()

    if "timeout" in name or "timeout" in low.split("\n")[0]:
        return "timeout", msg.split("\n")[0][:160]
    if "closed" in low or "targetclosed" in name:
        return "browser_closed", msg.split("\n")[0][:160]
    if ("net::err_" in low or "err_aborted" in low or "detached" in low
            or "econn" in low or "dns" in low or "getaddrinfo" in low):
        return "network_error", msg.split("\n")[0][:160]
    return "error", f"{type(e).__name__}: {msg.split(chr(10))[0][:160]}"


class ScrapeError(Exception):
    """Raised by @retry when a scraper exhausts its attempts."""
    def __init__(self, status: str, reason: str, attempts: int) -> None:
        super().__init__(reason)
        self.status   = status
        self.reason   = reason
        self.attempts = attempts

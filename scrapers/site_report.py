# Structured scan report: one status per site.
#
# Possible statuses:
#   ok                    jobs collected, no issue
#   ok_partial            jobs collected, but part of the site is inaccessible
#   empty                 site reachable but no jobs collected
#   requires_auth         content behind login
#   requires_manual_login manual session needed: python scraper.py --auth <site>
#   blocked               captcha / anti-bot
#   timeout               page did not respond in time
#   network_error         DNS / connection / abort
#   browser_closed        browser or page closed during scraping
#   selector_broken       page reached but DOM structure not recognized
#   disabled              scraper intentionally disabled, for example monster.ch
#   error                 unclassified error; see reason

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
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


class RunReport:
    """Collect results for all sites in one scan."""

    def __init__(self) -> None:
        self._results:   dict[str, SiteResult] = {}
        self._overrides: dict[str, dict]       = {}
        self.started = datetime.now()

    def set_status(self, site: str, status: str, reason: str = "",
                   final_url: str = "", screenshot: str = "") -> None:
        # Called by scrapers when they detect a gate (login, captcha)
        # without interrupting collection of jobs already found.
        self._overrides[site] = {
            "status": status, "reason": reason,
            "final_url": final_url, "screenshot": screenshot,
        }
        print(f"  [report] {site}: {status}" + (f" - {reason}" if reason else ""))

    def finish(self, site: str, jobs: int, duration_s: float,
               status: str = "", reason: str = "", attempts: int = 1) -> SiteResult:
        ov = self._overrides.get(site, {})
        if not status:
            status = "ok" if jobs > 0 else "empty"
        # A scraper override (gate/block) wins over calculated status.
        # If jobs were collected, downgrade the override to ok_partial.
        if ov:
            status = ov["status"]
            reason = ov["reason"] or reason
            if jobs > 0 and ov["status"] in ("requires_auth", "requires_manual_login", "blocked"):
                status = "ok_partial"
                reason = f"{ov['status']}: {ov['reason']}" if ov["reason"] else ov["status"]
        r = SiteResult(
            site=site, status=status, jobs=jobs,
            duration_s=round(duration_s, 1), attempts=attempts, reason=reason,
            final_url=ov.get("final_url", ""), screenshot=ov.get("screenshot", ""),
        )
        self._results[site] = r
        return r

    @property
    def results(self) -> list[SiteResult]:
        return list(self._results.values())

    def save(self, path: Path = REPORT_FILE) -> None:
        data = {
            "started":  self.started.isoformat(timespec="seconds"),
            "finished": datetime.now().isoformat(timespec="seconds"),
            "sites":    [asdict(r) for r in self.results],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[REPORT] Saved to {path}")

    def print_table(self) -> None:
        if not self._results:
            return
        W_SITE, W_STAT = 24, 22
        print("\n" + "=" * 78)
        print(f"  {'SITE':<{W_SITE}}{'STATUS':<{W_STAT}}{'JOBS':>5}  {'TIME':>7}  NOTE")
        print("-" * 78)
        for r in self.results:
            note = r.reason[:40] if r.reason else ""
            print(f"  {r.site:<{W_SITE}}{r.status:<{W_STAT}}{r.jobs:>5}"
                  f"  {r.duration_s:>6.0f}s  {note}")
        print("=" * 78)
        n_ok = sum(1 for r in self.results if r.status in ("ok", "ok_partial"))
        print(f"  {n_ok}/{len(self.results)} sites with jobs collected\n")


# Shared instance imported by scrapers to report gates and blocks.
run_report = RunReport()


def debug_artifacts(page: Page, tag: str) -> str:
    # Save a screenshot plus HTML in debug/ for diagnostics.
    # Return the screenshot path, or "" if screenshot capture fails.
    # Never raises: this is called on error paths.
    DEBUG_DIR.mkdir(exist_ok=True)
    shot = ""
    try:
        shot_path = DEBUG_DIR / f"{tag}.png"
        page.screenshot(path=str(shot_path))
        shot = str(shot_path)
    except Exception:
        pass
    try:
        (DEBUG_DIR / f"{tag}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    if shot:
        print(f"  [debug] {tag}: screenshot + HTML saved in {DEBUG_DIR}\\")
    return shot


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

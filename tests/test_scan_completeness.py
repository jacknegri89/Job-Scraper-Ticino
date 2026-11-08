"""Which cached jobs may be marked as gone, depending on how the source was read."""

from datetime import datetime, timedelta

import pytest

from job_lifecycle import merge_scan
from job_model import normalize_job
from job_pipeline import process_jobs
from preferences import SearchPreferences
from scrapers import italy_portals
from scrapers.site_report import RunReport

NOW = datetime(2026, 11, 8, 12, 0, 0)


def _cached_job() -> dict:
    seen = (NOW - timedelta(days=1)).isoformat()
    job = normalize_job({"title": "Sviluppatore Python", "company": "ACME SA", "city": "Chiasso", "date": "2026-11-01",
                         "url": "https://example.ch/1", "source": "jobs.ch"})
    job.update({"first_seen": seen, "last_seen": seen, "last_verified": seen, "status": "active"})
    return job


def _status_after_scan(source_outcome: str | None, current_raw_jobs: list[dict] | None = None) -> tuple[str, int]:
    """Status of the cached job after a scan that did not return it."""
    preferences = SearchPreferences()
    outcomes = {} if source_outcome is None else {"jobs.ch": source_outcome}
    new_jobs = process_jobs(current_raw_jobs or [], preferences).jobs
    jobs, _counts = merge_scan([_cached_job()], new_jobs, outcomes, preferences, NOW)
    assert len(jobs) == 1, "a cached job must never be deleted by one scan"
    return jobs[0]["status"], len(jobs)


def test_a_complete_search_with_results_lets_missing_jobs_expire() -> None:
    assert _status_after_scan("ok")[0] == "possibly_expired"


def test_a_complete_search_without_results_lets_missing_jobs_expire() -> None:
    # Before the fix "no_results" was treated like a failure and the job stayed "cached".
    assert _status_after_scan("no_results")[0] == "possibly_expired"


@pytest.mark.parametrize("outcome", [
    "blocked", "requires_auth", "requires_manual_login", "timeout", "network_error", "browser_closed",
    "selector_broken", "empty", "ok_partial", "error", "disabled", None,
])
def test_an_incomplete_or_missing_read_never_expires_a_job(outcome: str | None) -> None:
    assert _status_after_scan(outcome)[0] == "cached_source_unavailable"


def test_a_partial_read_that_returned_other_jobs_still_keeps_the_missing_one() -> None:
    other = {"title": "Sistemista", "company": "Beta SA", "city": "Chiasso", "date": "2026-11-05",
             "url": "https://example.ch/2", "source": "jobs.ch"}
    preferences = SearchPreferences()
    jobs, _counts = merge_scan([_cached_job()], process_jobs([other], preferences).jobs,
                               {"jobs.ch": "ok_partial"}, preferences, NOW)
    by_url = {job["url"]: job["status"] for job in jobs}
    assert by_url == {"https://example.ch/1": "cached_source_unavailable", "https://example.ch/2": "active"}


def test_one_unreadable_search_next_to_found_listings_is_reported_as_partial(monkeypatch) -> None:
    report = RunReport()
    monkeypatch.setattr(italy_portals, "run_report", report)

    italy_portals._report_outcome("indeed.it", [{"url": "https://it.indeed.com/1"}], ["found", "unreadable"])

    assert report.finish("indeed.it", 1, 1.0).status == "ok_partial"


def test_all_searches_found_listings_is_a_clean_read(monkeypatch) -> None:
    report = RunReport()
    monkeypatch.setattr(italy_portals, "run_report", report)

    italy_portals._report_outcome("indeed.it", [{"url": "https://it.indeed.com/1"}], ["found", "found"])

    assert report.finish("indeed.it", 1, 1.0).status == "ok"

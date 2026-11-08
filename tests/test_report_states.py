"""Scan report: a source is only 'read' when something trustworthy was read."""

import pytest

from exit_codes import EXIT_FAILURE, EXIT_PARTIAL, EXIT_SUCCESS, exit_code_for_overall_status
from scrapers.site_report import OVERALL_FAILURE, OVERALL_PARTIAL, OVERALL_SUCCESS, RunReport


def _finish(report: RunReport, site: str, jobs: int, status: str = "") -> str:
    return report.finish(site, jobs, 1.0, status=status).status


def test_a_failed_page_with_nothing_read_is_a_failure_not_a_partial_read() -> None:
    report = RunReport()
    report.set_status("jobs.ch", "ok_partial", "Page could not be loaded: TimeoutError")

    assert _finish(report, "jobs.ch", jobs=0) == "error"
    assert "no listing could be read" in report.results[0].reason
    assert report.overall_status() == OVERALL_FAILURE


def test_a_failed_page_next_to_listings_that_were_read_is_a_partial_read() -> None:
    report = RunReport()
    report.set_status("jobs.ch", "ok_partial", "Page could not be loaded: TimeoutError")

    assert _finish(report, "jobs.ch", jobs=12) == "ok_partial"
    assert report.overall_status() == OVERALL_PARTIAL


def test_a_search_that_finished_without_results_is_not_a_failure() -> None:
    report = RunReport()
    report.set_status("indeed.it", "no_results", "the portal reports no listings")

    assert _finish(report, "indeed.it", jobs=0) == "no_results"
    assert report.overall_status() == OVERALL_SUCCESS


def test_no_results_never_hides_an_earlier_failed_page() -> None:
    report = RunReport()
    report.set_status("indeed.it", "ok_partial", "a search page could not be opened")
    report.set_status("indeed.it", "no_results", "the portal reports no listings")

    assert _finish(report, "indeed.it", jobs=0) == "error"


def test_a_later_partial_note_never_hides_a_block() -> None:
    report = RunReport()
    report.set_status("linkedin.it", "blocked", "captcha")
    report.set_status("linkedin.it", "ok_partial", "a search page could not be opened")

    assert _finish(report, "linkedin.it", jobs=0) == "blocked"


def test_a_block_after_some_listings_were_read_is_a_partial_read() -> None:
    report = RunReport()
    report.set_status("linkedin.it", "blocked", "captcha")

    assert _finish(report, "linkedin.it", jobs=7) == "ok_partial"


def test_listings_next_to_a_selector_failure_are_a_partial_read_not_empty() -> None:
    report = RunReport()
    report.set_status("jobs.ch", "selector_broken", "no card on page 2")

    assert _finish(report, "jobs.ch", jobs=5) == "ok_partial"


def test_a_source_without_listings_and_without_proof_is_not_usable() -> None:
    report = RunReport()
    assert _finish(report, "orienta.ch", jobs=0) == "empty"
    assert report.overall_status() == OVERALL_FAILURE


@pytest.mark.parametrize(("statuses", "expected"), [
    ({"a": ("ok", 3), "b": ("no_results", 0)}, OVERALL_SUCCESS),
    ({"a": ("ok", 3), "b": ("timeout", 0)}, OVERALL_PARTIAL),
    ({"a": ("ok", 3), "b": ("ok_partial", 2)}, OVERALL_PARTIAL),
    ({"a": ("timeout", 0), "b": ("blocked", 0)}, OVERALL_FAILURE),
    ({"a": ("empty", 0), "b": ("selector_broken", 0)}, OVERALL_FAILURE),
    ({"a": ("ok", 3), "b": ("disabled", 0)}, OVERALL_SUCCESS),
])
def test_overall_status_for_each_important_combination(statuses: dict, expected: str) -> None:
    report = RunReport()
    for site, (status, jobs) in statuses.items():
        report.finish(site, jobs, 1.0, status=status)
    assert report.overall_status() == expected


@pytest.mark.parametrize(("overall", "code"), [
    (OVERALL_SUCCESS, EXIT_SUCCESS), (OVERALL_PARTIAL, EXIT_PARTIAL), (OVERALL_FAILURE, EXIT_FAILURE),
    ("something unexpected", EXIT_FAILURE),
])
def test_exit_code_follows_the_overall_status(overall: str, code: int) -> None:
    assert exit_code_for_overall_status(overall) == code
    assert len({EXIT_SUCCESS, EXIT_FAILURE, EXIT_PARTIAL}) == 3

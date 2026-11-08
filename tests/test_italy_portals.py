"""Indeed Italia and LinkedIn Italia: search URLs, job building and honest status reports."""

from urllib.parse import parse_qs, urlparse

import pytest

from scrapers import italy_portals
from scrapers.site_report import RunReport


@pytest.fixture
def report(monkeypatch: pytest.MonkeyPatch) -> RunReport:
    fresh_report = RunReport()
    monkeypatch.setattr(italy_portals, "run_report", fresh_report)
    return fresh_report


def test_indeed_url_uses_the_place_and_the_next_allowed_radius() -> None:
    url = italy_portals.indeed_search_url("sviluppatore python", "Barlassina", 30)
    query = parse_qs(urlparse(url).query)
    assert url.startswith("https://it.indeed.com/jobs?")
    assert query["q"] == ["sviluppatore python"]
    assert query["l"] == ["Barlassina"]
    assert query["radius"] == ["50"]


def test_indeed_url_without_a_starting_point_searches_the_whole_region() -> None:
    query = parse_qs(urlparse(italy_portals.indeed_search_url("sistemista", "", None)).query)
    assert query["l"] == ["Lombardia"]
    assert "radius" not in query


def test_linkedin_url_converts_kilometres_to_miles() -> None:
    url = italy_portals.linkedin_search_url("devops", "Barlassina", 30)
    query = parse_qs(urlparse(url).query)
    assert urlparse(url).netloc == "www.linkedin.com"
    assert query["location"] == ["Barlassina, Lombardia, Italia"]
    assert query["distance"] == ["25"]
    assert "distance" not in parse_qs(urlparse(italy_portals.linkedin_search_url("devops", "", 30)).query)


def test_search_terms_are_limited_and_blank_terms_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(italy_portals, "SEARCH_TERMS", ["  ", *[f"term {number}" for number in range(30)]])
    terms = italy_portals.search_terms()
    assert len(terms) == italy_portals.MAX_SEARCH_TERMS
    assert terms[0] == "term 0"


def test_indeed_job_keeps_the_written_salary_and_a_safe_link() -> None:
    job = italy_portals.build_indeed_job({
        "jk": "abcdef1234567890", "title": "Sviluppatore Python", "company": "ACME", "city": "Monza MB",
        "dateRaw": "", "salary": "28.000 € - 32.000 € all'anno",
    })
    assert job["source"] == "indeed.it"
    assert job["url"] == "https://it.indeed.com/viewjob?jk=abcdef1234567890"
    assert job["salary_text"] == "28.000 € - 32.000 € all'anno"
    assert job["date"] == ""
    assert italy_portals.build_indeed_job({"jk": "", "title": "x"}) is None
    assert italy_portals.build_indeed_job({"jk": "abcdef1234567890", "title": ""}) is None


def test_linkedin_job_requires_an_https_link() -> None:
    good = italy_portals.build_linkedin_job({"href": "https://it.linkedin.com/jobs/view/x-1", "title": "Dev",
                                             "company": "ACME", "city": "Milano", "dateRaw": "2026-10-20"})
    assert good["source"] == "linkedin.it"
    assert good["date"] == "2026-10-20"
    assert italy_portals.build_linkedin_job({"href": "javascript:alert(1)", "title": "Dev"}) is None
    assert italy_portals.build_linkedin_job({"href": "/jobs/view/1", "title": "Dev"}) is None


def test_zero_jobs_from_pages_that_say_no_results_is_not_an_error(report: RunReport) -> None:
    italy_portals._report_outcome("indeed.it", [], ["no_results", "no_results"])
    report.finish("indeed.it", 0, 1)
    assert report.results[0].status == "no_results"
    assert report.overall_status() == "success"


def test_zero_jobs_from_unrecognised_pages_is_a_broken_selector(report: RunReport) -> None:
    italy_portals._report_outcome("indeed.it", [], ["unreadable", "no_results"])
    report.finish("indeed.it", 0, 1)
    assert report.results[0].status == "selector_broken"
    assert report.overall_status() == "failure"


def test_a_block_keeps_its_own_status(report: RunReport) -> None:
    report.set_status("linkedin.it", "blocked", "anti-bot signal")
    italy_portals._report_outcome("linkedin.it", [], ["stopped"])
    report.finish("linkedin.it", 0, 1)
    assert report.results[0].status == "blocked"


def test_found_jobs_never_get_an_empty_status(report: RunReport) -> None:
    # Listings were read, so the source is not empty; one unreadable search makes it partial, not "ok".
    italy_portals._report_outcome("indeed.it", [{"url": "x"}], ["found", "unreadable"])
    report.finish("indeed.it", 1, 1)
    assert report.results[0].status == "ok_partial"


def test_overall_status_needs_every_site_read_for_success() -> None:
    report = RunReport()
    report.finish("a.it", 5, 1)
    report.finish("b.it", 0, 1)
    assert report.results[1].status == "empty"
    assert report.overall_status() == "partial"
    only_failures = RunReport()
    only_failures.finish("a.it", 0, 1, status="timeout")
    only_failures.finish("b.it", 0, 1, status="blocked")
    assert only_failures.overall_status() == "failure"
    everything_read = RunReport()
    everything_read.finish("a.it", 3, 1)
    everything_read.finish("b.it", 0, 1, status="no_results")
    assert everything_read.overall_status() == "success"

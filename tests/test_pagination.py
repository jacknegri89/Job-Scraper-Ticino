"""Shared page loop: partial reads, blocks and login walls stop a portal without losing listings."""

import pytest

from scrapers import jobs_ch, orienta_ch, pagination
from scrapers.site_report import RunReport


class FakePage:
    """Just enough of a Playwright page for the block and login checks."""

    def __init__(self, title: str = "Offerte di lavoro", url: str = "https://portal.example/jobs") -> None:
        self._title = title
        self.url = url

    def title(self) -> str:
        return self._title

    def query_selector(self, _selector: str) -> None:
        return None

    def screenshot(self, **_kwargs) -> None:
        return None

    def content(self) -> str:
        return ""

    def close(self) -> None:
        return None


@pytest.fixture
def report(monkeypatch: pytest.MonkeyPatch, tmp_path) -> RunReport:
    fresh_report = RunReport()
    monkeypatch.setattr(pagination, "run_report", fresh_report)
    monkeypatch.setattr(pagination, "debug_artifacts", lambda *_args: "")
    return fresh_report


def _scripted(results: list, requested: list[int], jobs: list):
    """add_page that returns or raises the scripted result of each page and records the request."""

    def add_page(page_number: int) -> bool:
        requested.append(page_number)
        outcome = results[page_number - 1]
        if isinstance(outcome, Exception):
            raise outcome
        if outcome:
            jobs.append(f"job-{page_number}")
        return outcome

    return add_page


def test_the_loop_ends_when_a_page_has_no_more_results(report: RunReport) -> None:
    requested, jobs = [], []

    pagination.collect_pages(FakePage(), "gigroup.ch", range(1, 10), _scripted([True, True, False], requested, jobs), jobs)

    assert requested == [1, 2, 3]
    assert report.finish("gigroup.ch", len(jobs), 1.0).status == "ok"


def test_a_block_on_the_second_page_keeps_page_one_and_requests_nothing_more(report: RunReport) -> None:
    requested, jobs = [], []
    page = FakePage(title="Attention Required! | Cloudflare")

    pagination.collect_pages(page, "gigroup.ch", range(1, 10), _scripted([True, False, True], requested, jobs), jobs)

    assert requested == [1, 2]
    assert jobs == ["job-1"]
    assert report.finish("gigroup.ch", len(jobs), 1.0).status == "ok_partial"


def test_a_block_on_the_first_page_is_a_blocked_source(report: RunReport) -> None:
    requested, jobs = [], []
    page = FakePage(title="Access Denied")

    pagination.collect_pages(page, "orienta.ch", range(1, 10), _scripted([False], requested, jobs), jobs)

    result = report.finish("orienta.ch", 0, 1.0)
    assert result.status == "blocked"
    assert "anti-bot" in result.reason


def test_a_login_wall_is_reported_and_never_bypassed(report: RunReport) -> None:
    requested, jobs = [], []
    page = FakePage(url="https://portal.example/login?next=/jobs")

    pagination.collect_pages(page, "orienta.ch", range(1, 10), _scripted([False], requested, jobs), jobs)

    assert report.finish("orienta.ch", 0, 1.0).status == "requires_auth"
    assert requested == [1]


def test_a_failing_page_after_some_listings_is_a_partial_read_and_keeps_them(report: RunReport) -> None:
    requested, jobs = [], []
    results = [True, True, TimeoutError("navigation timeout")]

    pagination.collect_pages(FakePage(), "jobscout24.ch", range(1, 10), _scripted(results, requested, jobs), jobs)

    assert jobs == ["job-1", "job-2"]
    assert requested == [1, 2, 3]
    result = report.finish("jobscout24.ch", len(jobs), 1.0)
    assert result.status == "ok_partial"
    assert "page 3" in result.reason


def test_a_failing_first_page_is_raised_so_the_retry_logic_can_run(report: RunReport) -> None:
    requested, jobs = [], []

    with pytest.raises(TimeoutError):
        pagination.collect_pages(FakePage(), "jobscout24.ch", range(1, 10),
                                 _scripted([TimeoutError("timeout")], requested, jobs), jobs)


def test_an_ordinary_empty_end_of_results_is_not_reported_as_a_problem(report: RunReport) -> None:
    assert pagination.report_gate_if_any(FakePage(), "carriera.ch") is False
    assert report.finish("carriera.ch", 3, 1.0).status == "ok"


def test_a_closed_page_during_the_gate_check_never_raises(report: RunReport) -> None:
    class ClosedPage:
        @property
        def url(self) -> str:
            raise RuntimeError("page closed")

        def title(self) -> str:
            raise RuntimeError("page closed")

    assert pagination.report_gate_if_any(ClosedPage(), "carriera.ch") is False


# --- the scrapers use the helper ----------------------------------------------------------

def test_orienta_keeps_the_first_pages_when_a_later_page_fails(monkeypatch, report: RunReport) -> None:
    monkeypatch.setattr(orienta_ch, "new_stealth_page", lambda _context: FakePage())
    calls: list[int] = []

    def fake_add_page_jobs(_page, page_num, _seen, all_jobs):
        calls.append(page_num)
        if page_num == 3:
            raise TimeoutError("navigation timeout")
        all_jobs.append({"url": f"https://www.orienta.ch/{page_num}"})
        return True

    monkeypatch.setattr(orienta_ch, "_add_page_jobs", fake_add_page_jobs)

    jobs = orienta_ch.scrape_orienta_ch(object())

    assert [job["url"] for job in jobs] == ["https://www.orienta.ch/1", "https://www.orienta.ch/2"]
    assert calls == [1, 2, 3]
    assert report.finish("orienta.ch", len(jobs), 1.0).status == "ok_partial"


def test_jobs_ch_stops_searching_other_terms_after_a_block(monkeypatch) -> None:
    searched: list[str] = []
    monkeypatch.setattr(jobs_ch, "new_stealth_page", lambda _context: FakePage())

    def fake_scrape_term(_page, term, _seen, _jobs) -> bool:
        searched.append(term)
        return term == "sistemista"  # the portal blocks us on the second term

    monkeypatch.setattr(jobs_ch, "_scrape_term", fake_scrape_term)

    jobs_ch.scrape_jobs_ch(object(), ["sviluppatore", "sistemista", "programmatore", "tecnico"])

    assert searched == ["sviluppatore", "sistemista"]

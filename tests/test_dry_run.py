"""Dry run: each portal gets an honest status without a full scrape."""

from contextlib import contextmanager

import pytest

import dry_run
import main
from scrapers.site_report import RunReport


class FakePage:
    def __init__(self, title: str = "Jobs", url: str = "https://www.jobs.ch/en/vacancies/",
                 has_selector: bool = True, goto_error: Exception | None = None) -> None:
        self._title = title
        self.url = url
        self._has_selector = has_selector
        self._goto_error = goto_error

    def goto(self, *_args, **_kwargs) -> None:
        if self._goto_error is not None:
            raise self._goto_error

    def wait_for_timeout(self, *_args) -> None:
        return None

    def wait_for_selector(self, *_args, **_kwargs) -> None:
        if not self._has_selector:
            raise TimeoutError("selector not found")

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


CURRENT_PAGE: dict[str, FakePage] = {}


@pytest.fixture
def report(monkeypatch: pytest.MonkeyPatch) -> RunReport:
    fresh_report = RunReport()
    monkeypatch.setattr(dry_run, "run_report", fresh_report)
    monkeypatch.setattr(dry_run, "dismiss_cookies", lambda *_args: None)
    monkeypatch.setattr("scrapers.new_stealth_page", lambda _context: CURRENT_PAGE["page"])
    monkeypatch.setattr("scrapers.site_report.debug_artifacts", lambda *_args: "")
    return fresh_report


def _probe(report: RunReport, monkeypatch, page: FakePage) -> str:
    CURRENT_PAGE["page"] = page
    dry_run._probe_browser_site(object(), "jobs.ch", "https://www.jobs.ch/en/vacancies/", "a.job", 0.0)
    return report.results[0].status


def test_a_portal_showing_results_is_ok(report, monkeypatch) -> None:
    assert _probe(report, monkeypatch, FakePage()) == "ok"


def test_a_page_without_the_result_selector_is_reported_as_changed(report, monkeypatch) -> None:
    assert _probe(report, monkeypatch, FakePage(has_selector=False)) == "selector_broken"


def test_a_block_page_is_reported_and_not_probed_further(report, monkeypatch) -> None:
    assert _probe(report, monkeypatch, FakePage(title="Access Denied")) == "blocked"


def test_a_login_wall_is_reported(report, monkeypatch) -> None:
    assert _probe(report, monkeypatch, FakePage(url="https://portal.example/login")) == "requires_auth"


def test_a_navigation_error_is_classified(report, monkeypatch) -> None:
    status = _probe(report, monkeypatch, FakePage(goto_error=TimeoutError("Timeout 30000ms exceeded")))
    assert status == "timeout"


def test_monster_is_disabled_and_the_index_probe_uses_the_scrapers_download(monkeypatch) -> None:
    fresh_report = RunReport()
    monkeypatch.setattr(dry_run, "run_report", fresh_report)
    monkeypatch.setattr(dry_run, "download_frontaliereticino_index", lambda: [{"slug": "a"}, {"slug": "b"}])

    dry_run._run_probes(object(), ["monster.ch", "frontaliereticino.ch", "unknown.example"])

    statuses = {result.site: result.status for result in fresh_report.results}
    assert statuses == {"monster.ch": "disabled", "frontaliereticino.ch": "ok", "unknown.example": "error"}


def test_every_portal_of_the_scan_has_a_probe() -> None:
    scanned_sites = {site for _label, site, _scraper in main.SCRAPERS}
    probed_sites = set(dry_run.PROBES) | {"monster.ch", "frontaliereticino.ch"}
    assert scanned_sites == probed_sites


def test_the_command_line_dry_run_probes_only_the_selected_sites(monkeypatch) -> None:
    probed: list[list[str]] = []
    monkeypatch.setattr(dry_run, "run_dry_run", probed.append)

    main._dry_run("indeed.it,linkedin")

    assert probed == [["linkedin.ch", "indeed.it", "linkedin.it"]]


def test_the_dry_run_saves_the_report_and_closes_the_browser(monkeypatch) -> None:
    fresh_report = RunReport()
    saved: list[bool] = []
    closed: list[bool] = []

    class Browser:
        def close(self) -> None:
            closed.append(True)

    @contextmanager
    def fake_playwright():
        yield object()

    monkeypatch.setattr(dry_run, "run_report", fresh_report)
    monkeypatch.setattr(fresh_report, "save", lambda *_: saved.append(True))
    monkeypatch.setattr(dry_run, "sync_playwright", fake_playwright)
    monkeypatch.setattr(dry_run, "create_browser_context", lambda _playwright: (Browser(), object()))

    dry_run.run_dry_run(["monster.ch"])

    assert saved == [True]
    assert closed == [True]
    assert fresh_report.overall_status() == "failure"  # only a disabled site: nothing was read

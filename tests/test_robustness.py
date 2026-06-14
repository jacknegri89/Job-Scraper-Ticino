"""Tests for retry, page guard, and run report behavior."""

import json
import sys
from pathlib import Path

import pytest
from pytest import MonkeyPatch

sys.path.insert(0, str(Path(__file__).parent.parent))

import scrapers as scrapers_mod
import scrapers.settings as cfg
from scrapers import retry
from scrapers.page_guard import detect_auth_gate, detect_block, dismiss_cookies
from scrapers.site_report import RunReport, ScrapeError, classify_exception


class FakeElement:
    def __init__(self, visible: bool = True) -> None:
        self._visible = visible
        self.clicks = 0

    def is_visible(self) -> bool:
        return self._visible

    def click(self) -> None:
        self.clicks += 1


class FakePage:
    def __init__(
        self,
        url: str = "https://example.com/",
        title: str = "Example",
        selectors: dict[str, FakeElement] | None = None,
    ) -> None:
        self.url = url
        self._title = title
        self.selectors = selectors or {}

    def title(self) -> str:
        return self._title

    def query_selector(self, selector: str) -> FakeElement | None:
        return self.selectors.get(selector)

    def wait_for_timeout(self, milliseconds: int) -> None:
        pass

    def evaluate(self, script: str) -> int:
        return 0


class FakeTimeoutError(Exception):
    pass


class TargetClosedError(Exception):
    pass


def test_classify_timeout() -> None:
    status, reason = classify_exception(FakeTimeoutError("Timeout 30000ms exceeded."))
    assert status == "timeout"
    assert "30000" in reason


def test_classify_browser_closed() -> None:
    status, _ = classify_exception(
        TargetClosedError("Target page, context or browser has been closed"))
    assert status == "browser_closed"


def test_classify_network() -> None:
    status, _ = classify_exception(
        Exception("Page.goto: net::ERR_ABORTED; maybe frame was detached?"))
    assert status == "network_error"


def test_classify_generic() -> None:
    status, reason = classify_exception(ValueError("boom"))
    assert status == "error"
    assert "ValueError" in reason


def test_auth_gate_from_login_url() -> None:
    page = FakePage(url="https://www.linkedin.com/authwall?x=1")
    assert detect_auth_gate(page) is not None


def test_auth_gate_from_indeed_title() -> None:
    page = FakePage(
        url="https://ch.indeed.com/jobs?start=15",
        title="Accedi | Account Indeed",
    )
    reason = detect_auth_gate(page)
    assert reason is not None and "title" in reason


def test_auth_gate_from_password_form() -> None:
    page = FakePage(selectors={'input[type="password"]': FakeElement()})
    assert detect_auth_gate(page) == "visible password form"


def test_auth_gate_normal_page() -> None:
    page = FakePage(
        url="https://www.jobs.ch/en/vacancies/?term=operaio",
        title="Posti vacanti in Ticino",
    )
    assert detect_auth_gate(page) is None


def test_block_captcha() -> None:
    page = FakePage(title="Attention Required! | Cloudflare")
    assert detect_block(page) is not None


def test_block_normal_page() -> None:
    page = FakePage(title="Offerte di lavoro Ticino")
    assert detect_block(page) is None


def test_cookie_domain_rule() -> None:
    button = FakeElement()
    page = FakePage(
        url="https://www.jobscout24.ch/de/jobs/ticino/",
        selectors={'button:has-text("Akzeptieren")': button},
    )
    clicked = dismiss_cookies(page, "jobscout24.ch")
    assert clicked == 'button:has-text("Akzeptieren")'
    assert button.clicks == 1


def test_cookie_generic_fallback() -> None:
    button = FakeElement()
    page = FakePage(
        url="https://www.unknown-site.ch/",
        selectors={'button#onetrust-reject-all-handler': button},
    )
    clicked = dismiss_cookies(page, "unknown-site")
    assert clicked == 'button#onetrust-reject-all-handler'
    assert button.clicks == 1


def test_cookie_no_banner() -> None:
    page = FakePage(url="https://www.example.ch/")
    assert dismiss_cookies(page, "example") is None


def test_cookie_hidden_button_is_ignored() -> None:
    button = FakeElement(visible=False)
    page = FakePage(
        url="https://www.example.ch/",
        selectors={'button:has-text("Rifiuta")': button},
    )
    assert dismiss_cookies(page, "example") is None
    assert button.clicks == 0


@pytest.fixture
def no_sleep(monkeypatch: MonkeyPatch) -> list[float]:
    sleeps: list[float] = []
    monkeypatch.setattr(scrapers_mod.time, "sleep", lambda seconds: sleeps.append(seconds))
    return sleeps


def test_retry_success_after_one_failure(
    no_sleep: list[float],
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(cfg, "MAX_ATTEMPTS", 2)
    calls = {"count": 0}

    @retry()
    def flaky() -> list[str]:
        calls["count"] += 1
        if calls["count"] == 1:
            raise ValueError("flaky")
        return ["job"]

    assert flaky() == ["job"]
    assert calls["count"] == 2
    assert len(no_sleep) == 1
    assert no_sleep[0] <= 6


def test_retry_exhausts_attempts(
    no_sleep: list[float],
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(cfg, "MAX_ATTEMPTS", 2)
    calls = {"count": 0}

    @retry()
    def always_fails() -> None:
        calls["count"] += 1
        raise ValueError("always broken")

    with pytest.raises(ScrapeError) as exc:
        always_fails()
    assert calls["count"] == 2
    assert exc.value.status == "error"
    assert exc.value.attempts == 2


def test_retry_browser_closed_without_retry(
    no_sleep: list[float],
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(cfg, "MAX_ATTEMPTS", 3)
    calls = {"count": 0}

    @retry()
    def closed() -> None:
        calls["count"] += 1
        raise TargetClosedError("Target page, context or browser has been closed")

    with pytest.raises(ScrapeError) as exc:
        closed()
    assert calls["count"] == 1
    assert exc.value.status == "browser_closed"
    assert no_sleep == []


def test_retry_caps_attempts_at_three(
    no_sleep: list[float],
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(cfg, "MAX_ATTEMPTS", 3)
    calls = {"count": 0}

    @retry(max_attempts=99)
    def always_fails() -> None:
        calls["count"] += 1
        raise ValueError("x")

    with pytest.raises(ScrapeError):
        always_fails()
    assert calls["count"] == 3


def test_report_ok_and_empty() -> None:
    report = RunReport()
    ok_result = report.finish("a.ch", jobs=10, duration_s=5.0)
    empty_result = report.finish("b.ch", jobs=0, duration_s=2.0)
    assert ok_result.status == "ok"
    assert empty_result.status == "empty"


def test_report_override_requires_auth() -> None:
    report = RunReport()
    report.set_status("linkedin.ch", "requires_manual_login", "authwall")
    result = report.finish("linkedin.ch", jobs=0, duration_s=3.0)
    assert result.status == "requires_manual_login"
    assert "authwall" in result.reason


def test_report_ok_partial_with_jobs_and_gate() -> None:
    report = RunReport()
    report.set_status("indeed.ch", "requires_auth", "page 2: login title")
    result = report.finish("indeed.ch", jobs=16, duration_s=8.0)
    assert result.status == "ok_partial"
    assert "requires_auth" in result.reason


def test_report_saves_json(tmp_path: Path) -> None:
    report = RunReport()
    report.finish("a.ch", jobs=3, duration_s=1.0)
    output_path = tmp_path / "report.json"
    report.save(output_path)
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["sites"][0]["site"] == "a.ch"
    assert data["sites"][0]["status"] == "ok"
    assert "started" in data and "finished" in data

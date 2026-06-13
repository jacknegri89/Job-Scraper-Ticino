"""
Test dell'infrastruttura di robustezza:
- classificazione eccezioni → stato
- rilevamento auth gate / blocco anti-bot
- chiusura cookie banner con regole per dominio
- decorator @retry (tentativi, backoff, errori irrecuperabili)
- RunReport (stati, override, ok_partial, salvataggio JSON)

Eseguire con:  python -m pytest tests/ -v
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scrapers.site_report import (
    RunReport, classify_exception, ScrapeError,
)
from scrapers.page_guard import detect_auth_gate, detect_block, dismiss_cookies
from scrapers import retry
import scrapers as scrapers_mod
import scrapers.settings as cfg


# ────────────────────────────────────────────────────────────────
# Finti oggetti Playwright
# ────────────────────────────────────────────────────────────────

class FakeElement:
    def __init__(self, visible=True):
        self._visible = visible
        self.clicks = 0

    def is_visible(self):
        return self._visible

    def click(self):
        self.clicks += 1


class FakePage:
    """Page minimale: url, title, selettori esistenti."""
    def __init__(self, url="https://example.com/", title="Example",
                 selectors=None):
        self.url = url
        self._title = title
        self.selectors = selectors or {}   # sel → FakeElement

    def title(self):
        return self._title

    def query_selector(self, sel):
        return self.selectors.get(sel)

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js):
        return 0


# ────────────────────────────────────────────────────────────────
# classify_exception
# ────────────────────────────────────────────────────────────────

class FakeTimeoutError(Exception):
    pass


class TargetClosedError(Exception):
    pass


def test_classify_timeout():
    status, reason = classify_exception(
        FakeTimeoutError("Timeout 30000ms exceeded."))
    assert status == "timeout"
    assert "30000" in reason


def test_classify_browser_closed():
    status, _ = classify_exception(
        TargetClosedError("Target page, context or browser has been closed"))
    assert status == "browser_closed"


def test_classify_network():
    status, _ = classify_exception(
        Exception("Page.goto: net::ERR_ABORTED; maybe frame was detached?"))
    assert status == "network_error"


def test_classify_generic():
    status, reason = classify_exception(ValueError("boom"))
    assert status == "error"
    assert "ValueError" in reason


# ────────────────────────────────────────────────────────────────
# detect_auth_gate / detect_block
# ────────────────────────────────────────────────────────────────

def test_auth_gate_da_url_login():
    page = FakePage(url="https://www.linkedin.com/authwall?x=1")
    assert detect_auth_gate(page) is not None


def test_auth_gate_da_titolo_indeed():
    page = FakePage(url="https://ch.indeed.com/jobs?start=15",
                    title="Accedi | Account Indeed")
    reason = detect_auth_gate(page)
    assert reason is not None and "titolo" in reason


def test_auth_gate_da_form_password():
    page = FakePage(selectors={'input[type="password"]': FakeElement()})
    reason = detect_auth_gate(page)
    assert reason == "form password visibile"


def test_auth_gate_pagina_normale():
    page = FakePage(url="https://www.jobs.ch/en/vacancies/?term=operaio",
                    title="Posti vacanti in Ticino")
    assert detect_auth_gate(page) is None


def test_block_captcha():
    page = FakePage(title="Attention Required! | Cloudflare")
    assert detect_block(page) is not None


def test_block_pagina_normale():
    page = FakePage(title="Offerte di lavoro Ticino")
    assert detect_block(page) is None


# ────────────────────────────────────────────────────────────────
# dismiss_cookies
# ────────────────────────────────────────────────────────────────

def test_cookie_regola_per_dominio():
    btn = FakeElement()
    page = FakePage(url="https://www.jobscout24.ch/de/jobs/ticino/",
                    selectors={'button:has-text("Akzeptieren")': btn})
    clicked = dismiss_cookies(page, "jobscout24.ch")
    assert clicked == 'button:has-text("Akzeptieren")'
    assert btn.clicks == 1


def test_cookie_fallback_generico():
    btn = FakeElement()
    page = FakePage(url="https://www.sito-sconosciuto.ch/",
                    selectors={'button#onetrust-reject-all-handler': btn})
    clicked = dismiss_cookies(page, "sito-sconosciuto")
    assert clicked == 'button#onetrust-reject-all-handler'
    assert btn.clicks == 1


def test_cookie_nessun_banner():
    page = FakePage(url="https://www.example.ch/")
    assert dismiss_cookies(page, "example") is None


def test_cookie_bottone_invisibile_ignorato():
    btn = FakeElement(visible=False)
    page = FakePage(url="https://www.example.ch/",
                    selectors={'button:has-text("Rifiuta")': btn})
    assert dismiss_cookies(page, "example") is None
    assert btn.clicks == 0


# ────────────────────────────────────────────────────────────────
# @retry
# ────────────────────────────────────────────────────────────────

@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(scrapers_mod.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


def test_retry_successo_dopo_un_fallimento(no_sleep, monkeypatch):
    monkeypatch.setattr(cfg, "MAX_ATTEMPTS", 2)
    calls = {"n": 0}

    @retry()
    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("flaky")
        return ["job"]

    assert flaky() == ["job"]
    assert calls["n"] == 2
    assert len(no_sleep) == 1            # un solo backoff
    assert no_sleep[0] <= 6              # backoff breve


def test_retry_esaurisce_tentativi(no_sleep, monkeypatch):
    monkeypatch.setattr(cfg, "MAX_ATTEMPTS", 2)
    calls = {"n": 0}

    @retry()
    def always_fails():
        calls["n"] += 1
        raise ValueError("sempre rotto")

    with pytest.raises(ScrapeError) as exc:
        always_fails()
    assert calls["n"] == 2
    assert exc.value.status == "error"
    assert exc.value.attempts == 2


def test_retry_browser_chiuso_niente_retry(no_sleep, monkeypatch):
    monkeypatch.setattr(cfg, "MAX_ATTEMPTS", 3)
    calls = {"n": 0}

    @retry()
    def closed():
        calls["n"] += 1
        raise TargetClosedError("Target page, context or browser has been closed")

    with pytest.raises(ScrapeError) as exc:
        closed()
    assert calls["n"] == 1               # nessun secondo tentativo
    assert exc.value.status == "browser_closed"
    assert no_sleep == []                # nessuna attesa inutile


def test_retry_massimo_tre_tentativi(no_sleep, monkeypatch):
    monkeypatch.setattr(cfg, "MAX_ATTEMPTS", 3)
    calls = {"n": 0}

    @retry(max_attempts=99)              # viene comunque limitato a 3
    def always_fails():
        calls["n"] += 1
        raise ValueError("x")

    with pytest.raises(ScrapeError):
        always_fails()
    assert calls["n"] == 3


# ────────────────────────────────────────────────────────────────
# RunReport
# ────────────────────────────────────────────────────────────────

def test_report_ok_e_empty():
    rep = RunReport()
    r1 = rep.finish("a.ch", jobs=10, duration_s=5.0)
    r2 = rep.finish("b.ch", jobs=0, duration_s=2.0)
    assert r1.status == "ok"
    assert r2.status == "empty"


def test_report_override_requires_auth():
    rep = RunReport()
    rep.set_status("linkedin.ch", "requires_manual_login", "authwall")
    r = rep.finish("linkedin.ch", jobs=0, duration_s=3.0)
    assert r.status == "requires_manual_login"
    assert "authwall" in r.reason


def test_report_ok_partial_con_job_e_gate():
    """Job raccolti + gate su pagine successive → ok_partial, non requires_auth."""
    rep = RunReport()
    rep.set_status("indeed.ch", "requires_auth", "pagina 2: titolo di login")
    r = rep.finish("indeed.ch", jobs=16, duration_s=8.0)
    assert r.status == "ok_partial"
    assert "requires_auth" in r.reason


def test_report_salvataggio_json(tmp_path):
    rep = RunReport()
    rep.finish("a.ch", jobs=3, duration_s=1.0)
    out = tmp_path / "report.json"
    rep.save(out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["sites"][0]["site"] == "a.ch"
    assert data["sites"][0]["status"] == "ok"
    assert "started" in data and "finished" in data

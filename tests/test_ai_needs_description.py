"""The AI rates a listing only from its text: never from the title alone, so never twice.

A listing whose description could not be read (not downloaded yet, blocked, attempts used up)
stays in the cache and on the dashboard, and costs nothing until its text arrives.
"""

import json
from types import SimpleNamespace

import pytest

import ai_analyzer
import main
from ai_analyzer import AI_KEY, AI_STATUS, AI_SUITABLE, analysis_key, profile_fingerprint
from job_lifecycle import DESCRIPTION_ATTEMPTS_FIELD, DESCRIPTION_LAST_ATTEMPT_FIELD
from job_model import normalize_job
from preferences import SearchPreferences

PROFILE = "Graduate with Python projects"
LISTING_TEXT = "Sviluppo di servizi in Python per i clienti dell'azienda, in un piccolo team di prodotto a Chiasso."
BLOCK_PAGE_TEXT = "Your request has been blocked."


class _CountingClient:
    """Stands in for OpenAI: counts the requests and always answers with a valid rating."""

    def __init__(self) -> None:
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_kwargs):
        self.calls += 1
        answer = json.dumps({"suitable": True, "reason": "fit", "description": "summary", "salary": None})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])


@pytest.fixture
def client(monkeypatch, tmp_path) -> _CountingClient:
    counting_client = _CountingClient()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(ai_analyzer, "_DELAY_BETWEEN_CALLS", 0)
    monkeypatch.setattr(ai_analyzer, "CANDIDATE_PROFILE_OVERRIDE", PROFILE)
    monkeypatch.setattr(ai_analyzer, "_create_openai_client", lambda: counting_client)
    monkeypatch.setattr(main, "_AI_ENABLED", True)
    monkeypatch.setattr(main, "_AI_MAX_PER_RUN", 25)
    monkeypatch.setattr(main, "_ACTIVE_SOURCES", None)
    monkeypatch.setattr(main, "_PREFERENCES", SearchPreferences())
    monkeypatch.setattr(main, "CACHE_FILE", tmp_path / "jobs_cache.json")
    monkeypatch.setattr(main, "_open_dashboard", lambda *_args: None)
    return counting_client


def _job(number: int = 1, **extra: object) -> dict:
    job = normalize_job({"title": f"Sviluppatore Python {number}", "company": "ACME SA", "city": "Chiasso",
                         "date": "2026-11-05", "url": f"https://www.jobs.ch/it/annuncio/{number}",
                         "source": "jobs.ch"})
    job["status"] = "active"
    job.update(extra)
    return job


def _run(jobs: list[dict]) -> None:
    main._finalize_jobs(jobs, main.datetime.now())


def test_a_listing_without_a_description_is_never_sent(client) -> None:
    with_text = _job(1, description=LISTING_TEXT)
    without_text = _job(2)
    only_spaces = _job(3, description="   ")

    ai_analyzer.analyze_jobs([with_text, without_text, only_spaces])

    assert client.calls == 1
    assert with_text[AI_SUITABLE] is True
    assert without_text[AI_SUITABLE] is None
    assert only_spaces[AI_SUITABLE] is None


def test_used_up_download_attempts_do_not_allow_a_rating_from_the_title(client) -> None:
    gave_up = _job(1, **{DESCRIPTION_ATTEMPTS_FIELD: main.MAX_DESCRIPTION_ATTEMPTS,
                         DESCRIPTION_LAST_ATTEMPT_FIELD: "2026-11-09T08:00:00"})

    _run([gave_up])

    assert client.calls == 0
    assert gave_up[AI_SUITABLE] is None


def test_a_blocked_page_kept_as_text_by_an_old_cache_is_not_sent(client) -> None:
    blocked = _job(1, description=BLOCK_PAGE_TEXT)
    source_unreadable = _job(2, status="cached_source_unavailable")

    _run([blocked, source_unreadable])

    assert client.calls == 0


def test_the_listing_stays_in_the_cache_and_on_the_dashboard_without_its_text(client, tmp_path) -> None:
    job = _job(1)

    _run([job])

    saved = json.loads((tmp_path / "jobs_cache.json").read_text(encoding="utf-8"))
    assert [item["url"] for item in saved] == [job["url"]]
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Sviluppatore Python 1" in page
    assert "The portal did not give the text of this listing" in page
    assert client.calls == 0


def test_one_listing_is_paid_for_once_however_late_its_text_arrives(client) -> None:
    job = _job(1)
    _run([job])
    _run([job])
    assert client.calls == 0

    job["description"] = LISTING_TEXT
    _run([job])
    assert client.calls == 1

    _run([job])
    assert client.calls == 1, "an unchanged listing is never sent again"


def test_a_rating_already_in_the_cache_for_the_same_listing_is_kept(client) -> None:
    """Made by an earlier version from the title alone: still the rating of this exact listing."""
    job = _job(1)
    job.update({AI_SUITABLE: False, "ai_reason": "needs five years", AI_STATUS: "analyzed"})
    job[AI_KEY] = analysis_key(job, profile_fingerprint(PROFILE))

    _run([job])

    assert client.calls == 0
    assert job[AI_SUITABLE] is False
    assert job["ai_reason"] == "needs five years"


def test_a_rating_made_from_text_that_is_gone_is_cleared_and_not_bought_again(client) -> None:
    """The old cache rated a login wall; the wall was removed, so that rating describes nothing."""
    job = _job(1)
    job.update({AI_SUITABLE: True, "ai_reason": "rated a login wall", AI_STATUS: "analyzed",
                AI_KEY: "key-of-the-text-that-was-removed"})

    _run([job])

    assert client.calls == 0
    assert job[AI_SUITABLE] is None
    assert job[AI_STATUS] == "stale"


def test_the_per_run_limit_counts_only_listings_that_can_be_rated(client, monkeypatch) -> None:
    monkeypatch.setattr(main, "_AI_MAX_PER_RUN", 2)
    without_text = [_job(number) for number in range(1, 6)]
    with_text = [_job(number, description=LISTING_TEXT + f" Posizione {number}.") for number in range(6, 9)]

    _run(without_text + with_text)

    assert client.calls == 2
    assert all(job[AI_SUITABLE] is None for job in without_text)

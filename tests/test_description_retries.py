"""Listing pages that keep failing are retried a few times, then left alone for a while.

Also here: a listing is called "gone" only on wording that a removed page really uses.
"""

from datetime import datetime, timedelta

import pytest

import main
import scrapers
from job_lifecycle import DESCRIPTION_ATTEMPTS_FIELD, DESCRIPTION_LAST_ATTEMPT_FIELD, merge_scan
from job_model import normalize_job
from job_pipeline import process_jobs
from preferences import SearchPreferences

NOW = datetime(2026, 11, 10, 9, 0, 0)
URL = "https://www.jobs.ch/it/annuncio/1"
REAL_TEXT = "Sviluppo di servizi in Python per i clienti dell'azienda, in un piccolo team di prodotto a Chiasso."


def _job(**extra: object) -> dict:
    job = normalize_job({"title": "Sviluppatore Python", "company": "ACME SA", "city": "Chiasso",
                         "date": "2026-11-01", "url": URL, "source": "jobs.ch"})
    job["status"] = "active"
    job.update(extra)
    return job


def _use_settings(monkeypatch) -> None:
    monkeypatch.setattr(main, "_PREFERENCES", SearchPreferences())
    monkeypatch.setattr(main, "_ACTIVE_SOURCES", None)


def _download(monkeypatch, jobs: list[dict], page_text: str, email: str = "") -> list[str]:
    opened: list[str] = []

    def fake_fetch(_context, url):
        opened.append(url)
        return {"description": page_text, "email": email}

    monkeypatch.setattr(main, "fetch_description", fake_fetch)
    main._download_descriptions(None, jobs)
    return opened


def test_a_page_that_gave_no_text_counts_as_one_failed_attempt(monkeypatch) -> None:
    _use_settings(monkeypatch)
    job = _job()

    opened = _download(monkeypatch, [job], page_text="")

    assert opened == [URL]
    assert job[DESCRIPTION_ATTEMPTS_FIELD] == 1
    assert job[DESCRIPTION_LAST_ATTEMPT_FIELD]


def test_after_three_failures_the_page_is_left_alone_until_the_waiting_days_pass(monkeypatch) -> None:
    _use_settings(monkeypatch)
    yesterday = (datetime.now() - timedelta(days=1)).isoformat()
    long_ago = (datetime.now() - timedelta(days=main.DESCRIPTION_RETRY_DAYS + 1)).isoformat()
    resting = _job(**{DESCRIPTION_ATTEMPTS_FIELD: main.MAX_DESCRIPTION_ATTEMPTS,
                      DESCRIPTION_LAST_ATTEMPT_FIELD: yesterday})
    due_again = _job(url="https://www.jobs.ch/it/annuncio/2",
                     **{DESCRIPTION_ATTEMPTS_FIELD: main.MAX_DESCRIPTION_ATTEMPTS,
                        DESCRIPTION_LAST_ATTEMPT_FIELD: long_ago})

    opened = _download(monkeypatch, [resting, due_again], page_text="")

    assert opened == ["https://www.jobs.ch/it/annuncio/2"]
    assert resting[DESCRIPTION_ATTEMPTS_FIELD] == main.MAX_DESCRIPTION_ATTEMPTS
    assert due_again[DESCRIPTION_ATTEMPTS_FIELD] == main.MAX_DESCRIPTION_ATTEMPTS + 1


def test_a_description_that_arrives_clears_the_failure_count(monkeypatch) -> None:
    _use_settings(monkeypatch)
    job = _job(**{DESCRIPTION_ATTEMPTS_FIELD: 2, DESCRIPTION_LAST_ATTEMPT_FIELD: "2026-11-09T08:00:00"})

    _download(monkeypatch, [job], page_text=REAL_TEXT, email="lavoro@acme.example")

    assert job["description"] == REAL_TEXT
    assert job["email"] == "lavoro@acme.example"
    assert DESCRIPTION_ATTEMPTS_FIELD not in job
    assert DESCRIPTION_LAST_ATTEMPT_FIELD not in job


def test_listings_never_tried_are_opened_before_those_that_already_failed(monkeypatch) -> None:
    _use_settings(monkeypatch)
    monkeypatch.setattr(main, "MAX_DESCRIPTIONS_PER_RUN", 1)
    failed_before = _job(**{DESCRIPTION_ATTEMPTS_FIELD: 2})
    never_tried = _job(url="https://www.jobs.ch/it/annuncio/2")

    opened = _download(monkeypatch, [failed_before, never_tried], page_text="")

    assert opened == ["https://www.jobs.ch/it/annuncio/2"]


def test_a_failed_page_does_not_erase_an_email_found_earlier(monkeypatch) -> None:
    _use_settings(monkeypatch)
    job = _job(email="lavoro@acme.example")

    _download(monkeypatch, [job], page_text="")

    assert job["email"] == "lavoro@acme.example"


def test_a_damaged_counter_in_the_cache_is_read_as_zero(monkeypatch) -> None:
    _use_settings(monkeypatch)
    job = _job(**{DESCRIPTION_ATTEMPTS_FIELD: "many", DESCRIPTION_LAST_ATTEMPT_FIELD: "not a date"})

    opened = _download(monkeypatch, [job], page_text="")

    assert opened == [URL]
    assert job[DESCRIPTION_ATTEMPTS_FIELD] == 1


def test_the_failure_count_survives_the_next_scan() -> None:
    cached = _job(first_seen="2026-11-08T09:00:00", last_seen="2026-11-08T09:00:00",
                  **{DESCRIPTION_ATTEMPTS_FIELD: 3, DESCRIPTION_LAST_ATTEMPT_FIELD: "2026-11-08T09:00:00"})
    fresh = process_jobs([{"title": "Sviluppatore Python", "company": "ACME SA", "city": "Chiasso",
                           "date": "2026-11-01", "url": URL, "source": "jobs.ch"}], SearchPreferences()).jobs

    jobs, _counts = merge_scan([cached], fresh, {"jobs.ch": "ok"}, SearchPreferences(), NOW)

    assert jobs[0][DESCRIPTION_ATTEMPTS_FIELD] == 3
    assert jobs[0][DESCRIPTION_LAST_ATTEMPT_FIELD] == "2026-11-08T09:00:00"


# ---- "gone" needs wording that a removed page really uses


class _Page:
    def __init__(self, text: str, url: str = URL) -> None:
        self.text = text
        self.url = url

    def evaluate(self, _script: str) -> str:
        return self.text


@pytest.mark.parametrize("listing_text", [
    "Analisi dei log: quando un file is not found il servizio deve riprovare.",
    "You will fix bugs such as '404 Not Found' responses in our public API.",
    "Requisiti: saper gestire errori come Resource Not Found e timeouts.",
])
def test_a_listing_that_only_mentions_not_found_is_still_online(listing_text: str) -> None:
    assert scrapers._listing_verdict(_Page(listing_text), 200, URL) == "available"


@pytest.mark.parametrize("removed_page_text", [
    "Job not found",
    "Page not found. Back to the search.",
    "Pagina non trovata",
    "Annuncio non trovato",
    "This job is no longer available",
    "Questa offerta non è più disponibile",
    "Diese Stelle ist nicht mehr verfügbar",
])
def test_the_wording_of_a_removed_listing_is_recognised(removed_page_text: str) -> None:
    assert scrapers._listing_verdict(_Page(removed_page_text), 200, URL) == "gone"


def test_a_missing_page_is_gone_and_an_error_or_a_redirect_is_unknown() -> None:
    assert scrapers._listing_verdict(_Page(""), 404, URL) == "gone"
    assert scrapers._listing_verdict(_Page(""), 410, URL) == "gone"
    assert scrapers._listing_verdict(_Page(REAL_TEXT), 503, URL) == "unknown"
    assert scrapers._listing_verdict(_Page(REAL_TEXT, "https://www.jobs.ch/it/login"), 200, URL) == "unknown"

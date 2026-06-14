"""Tests for city normalization, filtering, deduplication, and categories."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from job_filter import categorize_job, filter_jobs, is_valid_job, normalize_city, normalize_url


def _job(**extra: object) -> dict:
    base = {
        "title": "Operaio",
        "company": "ACME SA",
        "city": "Chiasso",
        "date": "2026-06-10",
        "url": "https://example.ch/job/1",
        "source": "jobs.ch",
    }
    base.update(extra)
    return base


def test_normalize_city_accepts_portal_formats() -> None:
    assert normalize_city("Chiasso") == "chiasso"
    assert normalize_city("6850 Chiasso") == "chiasso"
    assert normalize_city("Chiasso, TI") == "chiasso"
    assert normalize_city("Chiasso (TI)") == "chiasso"
    assert normalize_city("Chiasso TI") == "chiasso"
    assert normalize_city("Mendrisiotto - Chiasso") == "chiasso"


def test_allowed_city_passes() -> None:
    assert is_valid_job(_job(city="Mendrisio")) is True


def test_out_of_area_city_is_rejected() -> None:
    assert is_valid_job(_job(city="Lugano")) is False
    assert is_valid_job(_job(city="Zurigo")) is False


def test_italian_portal_is_rejected() -> None:
    assert is_valid_job(_job(url="https://www.subito.it/annuncio/5")) is False


def test_identical_url_is_deduplicated() -> None:
    first = _job()
    second = _job(title="Operaio copy")
    assert len(filter_jobs([first, second])) == 1


def test_same_content_across_portals_is_deduplicated() -> None:
    first = _job(url="https://www.jobs.ch/job/1")
    second = _job(url="https://www.jobscout24.ch/job/9", source="jobscout24.ch")
    assert len(filter_jobs([first, second])) == 1


def test_agency_jobs_are_not_deduplicated_by_title_only() -> None:
    first = _job(
        source="randstad.ch",
        company="Randstad SA",
        url="https://www.randstad.ch/it/lavoro/operaio_chiasso_aaaa1111-22bb/",
    )
    second = _job(
        source="randstad.ch",
        company="Randstad SA",
        url="https://www.randstad.ch/it/lavoro/operaio_chiasso_cccc3333-44dd/",
    )
    assert len(filter_jobs([first, second])) == 2


def test_jobs_are_sorted_by_newest_date_first() -> None:
    old_job = _job(title="Saldatore", date="2026-05-01", url="https://x.ch/1")
    new_job = _job(title="Magazziniere", date="2026-06-12", url="https://x.ch/2")
    eu_date_job = _job(title="Elettricista", date="11.06.2026", url="https://x.ch/3")
    result = filter_jobs([old_job, new_job, eu_date_job])
    assert [job["date"] for job in result] == ["2026-06-12", "11.06.2026", "2026-05-01"]


def test_tracking_parameters_do_not_change_normalized_url() -> None:
    clean_url = normalize_url("https://x.ch/job?id=5")
    tracked_url = normalize_url("https://x.ch/job?id=5&utm_source=feed&utm_medium=x")
    assert clean_url == tracked_url


def test_category_from_title() -> None:
    assert categorize_job("Magazziniere turno notte") == "logistics"
    assert categorize_job("Elettricista AFC") == "tech"
    assert categorize_job("Cameriere di sala") == "food_service"
    assert categorize_job("Direttore generale") == "other"

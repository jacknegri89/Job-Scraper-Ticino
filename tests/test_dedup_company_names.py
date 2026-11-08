"""De-duplication compares whole company names, keeps every link and keeps AI results."""

import pytest

from job_dedup import _company_key, deduplicate
from job_model import normalize_job


def _job(source: str, url: str, company: str, title: str = "Sviluppatore Python", **extra: object) -> dict:
    base = {"title": title, "company": company, "city": "Monza MB", "date": "2026-11-05", "url": url, "source": source}
    base.update(extra)
    return normalize_job(base)


def test_companies_sharing_a_long_prefix_are_different_companies() -> None:
    first = _job("indeed.it", "https://it.indeed.com/1", "Gruppo Tecnologico Lombardo Alfa Srl")
    second = _job("linkedin.it", "https://it.linkedin.com/1", "Gruppo Tecnologico Lombardo Beta Srl")

    unique, duplicates = deduplicate([first, second])

    assert len(unique) == 2
    assert duplicates == []


def test_the_same_company_written_differently_on_two_portals_is_one_job() -> None:
    first = _job("indeed.it", "https://it.indeed.com/1", "Esempio Servizi S.r.l.")
    second = _job("linkedin.it", "https://it.linkedin.com/1", "ESEMPIO SERVIZI SRL")

    unique, duplicates = deduplicate([first, second])

    assert len(unique) == 1
    assert len(duplicates) == 1
    assert {reference["source"] for reference in unique[0]["sources"]} == {"indeed.it", "linkedin.it"}


def test_different_positions_of_the_same_company_stay_separate() -> None:
    first = _job("indeed.it", "https://it.indeed.com/1", "ACME SA", "Sviluppatore Python")
    second = _job("linkedin.it", "https://it.linkedin.com/2", "ACME SA", "Sistemista Linux")

    assert len(deduplicate([first, second])[0]) == 2


def test_same_company_in_another_place_stays_separate() -> None:
    first = _job("indeed.it", "https://it.indeed.com/1", "ACME SA")
    second = _job("linkedin.it", "https://it.linkedin.com/1", "ACME SA", city="Milano")

    assert len(deduplicate([first, second])[0]) == 2


@pytest.mark.parametrize(("name", "expected"), [
    ("Esempio Servizi S.r.l.", "esempioservizi"),
    ("Esempio Servizi SRL", "esempioservizi"),
    ("Nasa", "nasa"),
    ("SA", "sa"),
    ("Beta S.p.A.", "beta"),
    ("Acme AG", "acme"),
    ("", ""),
])
def test_company_key_drops_only_a_trailing_legal_form(name: str, expected: str) -> None:
    assert _company_key(name) == expected


def test_an_analysis_that_only_the_other_copy_has_is_not_lost() -> None:
    analysed_copy = _job("indeed.it", "https://it.indeed.com/1", "ACME SA",
                         ai_suitable=True, ai_reason="Good fit", ai_key="abc", ai_status="analyzed",
                         first_seen="2026-11-01T08:00:00", status="active")
    new_copy = _job("linkedin.it", "https://it.linkedin.com/1", "ACME SA", date="2026-11-07",
                    first_seen="2026-11-08T08:00:00", status="active")

    unique, _duplicates = deduplicate([new_copy, analysed_copy])

    assert len(unique) == 1
    assert unique[0]["ai_suitable"] is True
    assert unique[0]["ai_reason"] == "Good fit"
    assert unique[0]["first_seen"] == "2026-11-01T08:00:00"
    assert len(unique[0]["sources"]) == 2


def test_merging_does_not_overwrite_an_analysis_the_main_copy_already_has() -> None:
    first = _job("indeed.it", "https://it.indeed.com/1", "ACME SA", date="2026-11-07", ai_suitable=False,
                 ai_reason="Not a fit", ai_key="k1", ai_status="analyzed")
    second = _job("linkedin.it", "https://it.linkedin.com/1", "ACME SA", ai_suitable=True,
                  ai_reason="Fit", ai_key="k2", ai_status="analyzed")

    unique, _duplicates = deduplicate([first, second])

    assert unique[0]["ai_reason"] == "Not a fit"

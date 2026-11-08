"""Filters stay consistent once the full description is known, and work mode is read carefully."""

import pytest

import main
from job_model import normalize_job, refresh_from_description
from job_pipeline import exclusion_reason, process_jobs
from preferences import SearchPreferences
from work_mode import work_mode_from_text, work_mode_of_job

NO_SENIOR = frozenset({"junior", "mid", "manager", "unknown"})
ONLY_JUNIOR_OR_UNKNOWN = frozenset({"junior", "unknown"})


def _raw(title: str = "Software Engineer", **extra: object) -> dict:
    base = {"title": title, "company": "ACME SA", "city": "Chiasso", "date": "2026-11-05",
            "url": "https://example.ch/1", "source": "jobs.ch"}
    base.update(extra)
    return base


def test_description_with_five_years_turns_an_unknown_seniority_into_senior() -> None:
    job = normalize_job(_raw())
    assert job["seniority"] == "unknown"

    job["description"] = "Cerchiamo una persona con almeno 5 anni di esperienza in Python."
    refresh_from_description(job)

    assert job["seniority"] == "senior"
    assert job["seniority_evidence"].startswith("description")


def test_a_senior_listing_excluded_by_the_user_disappears_after_the_description_is_read() -> None:
    preferences = SearchPreferences(seniority_levels=NO_SENIOR)
    job = normalize_job(_raw())
    assert exclusion_reason(job, preferences) == ""

    job["description"] = "Richiesti 6 anni di esperienza come sviluppatore."
    refresh_from_description(job)

    assert exclusion_reason(job, preferences) == "seniority"


def test_the_full_list_keeps_the_job_in_the_cache_but_hides_it(monkeypatch) -> None:
    monkeypatch.setattr(main, "_PREFERENCES", SearchPreferences(seniority_levels=NO_SENIOR))
    monkeypatch.setattr(main, "_ACTIVE_SOURCES", None)
    job = normalize_job(_raw(description="Almeno 7 anni di esperienza richiesti."))
    refresh_from_description(job)
    kept = [job, normalize_job(_raw("Junior developer", url="https://example.ch/2"))]

    visible = main._visible_jobs(kept)

    assert [item["title"] for item in visible] == ["Junior developer"]
    assert len(kept) == 2


def test_an_unknown_seniority_is_not_discarded_before_the_description_is_downloaded() -> None:
    preferences = SearchPreferences(seniority_levels=frozenset({"junior", "mid"}))

    result = process_jobs([_raw()], preferences)

    assert [job["title"] for job in result.jobs] == ["Software Engineer"]
    assert not result.stats["jobs.ch"].excluded


def test_a_known_seniority_outside_the_wanted_levels_is_still_excluded_early() -> None:
    preferences = SearchPreferences(seniority_levels=frozenset({"junior", "mid"}))

    result = process_jobs([_raw("Senior Software Engineer")], preferences)

    assert result.jobs == []
    assert dict(result.stats["jobs.ch"].excluded) == {"seniority": 1}


def test_a_job_with_a_description_is_filtered_completely_at_once() -> None:
    preferences = SearchPreferences(seniority_levels=frozenset({"junior"}))

    result = process_jobs([_raw()], preferences)
    assert len(result.jobs) == 1  # no description yet: unknown seniority waits

    result = process_jobs([_raw(description="Servono almeno 6 anni di esperienza.")], preferences)
    assert result.jobs == []


def test_contract_recognised_only_in_the_description_is_filtered_after_enrichment() -> None:
    preferences = SearchPreferences(contract_types=frozenset({"permanent", "unknown"}))
    job = normalize_job(_raw("Sviluppatore"))
    assert exclusion_reason(job, preferences) == ""

    job["description"] = "Si offre uno stage di sei mesi presso la nostra sede."
    refresh_from_description(job)

    assert job["contract_type"] == "internship"
    assert exclusion_reason(job, preferences) == "contract_type"


def test_unknown_contract_waits_for_the_description_before_an_early_exclusion() -> None:
    preferences = SearchPreferences(contract_types=frozenset({"permanent"}))

    assert len(process_jobs([_raw("Sviluppatore")], preferences).jobs) == 1


def test_the_description_downloaded_in_this_run_updates_the_job(monkeypatch) -> None:
    job = normalize_job(_raw())
    monkeypatch.setattr(main, "fetch_description",
                        lambda _context, _url: {"description": "Minimo 5 anni di esperienza.", "email": ""})

    main._download_one_description(None, job, 0, [job], 0.0, [])

    assert job["seniority"] == "senior"


# --- work mode -------------------------------------------------------------------------

@pytest.mark.parametrize(("location", "expected"), [
    ("Remoto in Lomazzo", "remote"), ("Ibrido a Milano", "hybrid"), ("Chiasso", ""), ("", ""),
])
def test_the_location_text_decides_first(location: str, expected: str) -> None:
    assert work_mode_of_job(location, "Developer", "")[0] == expected


@pytest.mark.parametrize("text", [
    "Posizione 100% remoto per sviluppatori Python.",
    "This is a fully remote role.",
    "Lavoro interamente da remoto.",
])
def test_a_clear_remote_statement_in_the_description_is_trusted(text: str) -> None:
    mode, evidence = work_mode_of_job("Milano", "Developer", text)
    assert mode == "remote"
    assert evidence.startswith("text:")


@pytest.mark.parametrize("text", [
    "Modalità ibrida: 3 giorni in ufficio.", "Hybrid working model.",
])
def test_a_clear_hybrid_statement_in_the_description_is_trusted(text: str) -> None:
    assert work_mode_of_job("Milano", "Developer", text)[0] == "hybrid"


@pytest.mark.parametrize("text", [
    "Non è previsto il lavoro da remoto: presenza in sede obbligatoria.",
    "No remote work. On site only.",
    "Senza smart working né telelavoro.",
    "Fully remote is not possible for this role, we work in our office.",
    "Ci piace lo smart working ma la sede è a Monza.",
    "Our clients work remotely across Europe.",
    "",
])
def test_negative_generic_or_unrelated_mentions_leave_the_mode_unknown(text: str) -> None:
    assert work_mode_from_text(text)[0] == ""


def test_a_remote_description_makes_the_job_remote_and_hides_it_by_default() -> None:
    job = normalize_job(_raw(description="Posizione 100% remoto."))
    assert job["work_mode"] == "remote"
    assert exclusion_reason(job, SearchPreferences()) == "remote"
    assert exclusion_reason(job, SearchPreferences(include_remote=True)) == ""


def test_no_place_or_distance_is_invented_for_a_remote_description() -> None:
    job = normalize_job(_raw(city="", description="Posizione 100% remoto."))
    assert job["place_name"] == ""
    assert job["location_certainty"] == "unknown"

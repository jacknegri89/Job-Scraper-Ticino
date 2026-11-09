"""Cleaning a description kept by an older scan changes the text and what is read from it, nothing else."""

import copy

import ai_analyzer
import main
from description_text import LINE_SEPARATOR
from job_model import normalize_job

WALL = LINE_SEPARATOR.join([
    "Iscriviti o accedi per trovare il tuo prossimo lavoro", "Email o telefono", "Password",
    "Hai dimenticato la password? Accedi", "Non hai un account LinkedIn? Iscriviti ora",
])
REAL_TEXT = ("Lavorerai con il team dati su modelli di previsione della domanda e pipeline in Python. "
             "Richiesta laurea magistrale in ambito quantitativo.")

# What is read from the description is allowed to change; everything else must stay as it was.
DERIVED_FIELDS = {"description", "category", "seniority", "seniority_evidence", "contract_type",
                  "work_mode", "work_mode_evidence"}


def _cached_job(description: str, **extra: object) -> dict:
    job = {
        "title": "Data Scientist", "company": "Acme", "city": "Milano", "date": "2026-11-05",
        "url": "https://it.linkedin.com/jobs/view/1", "source": "linkedin.it",
        "first_seen": "2026-11-01T08:00:00", "last_seen": "2026-11-08T08:00:00", "last_verified": "2026-11-08T09:00:00",
        "status": "active", "status_reason": "seen in the latest scan", "email": "jobs@acme.example",
        "ai_suitable": True, "ai_reason": "Good fit", "ai_description": "Previsione della domanda.",
        "ai_salary": {"amount": 4200, "currency": "EUR", "period": "month"}, "ai_key": "abc123", "ai_status": "analyzed",
        "description": description,
    }
    job.update(extra)
    return job


def test_cleaning_a_cached_description_keeps_every_other_field() -> None:
    cached = _cached_job(WALL + LINE_SEPARATOR + "Candidati" + LINE_SEPARATOR + REAL_TEXT)
    before = copy.deepcopy(cached)

    cleaned = normalize_job(cached)

    for name, value in before.items():
        if name in DERIVED_FIELDS:
            continue
        assert cleaned[name] == value, name
    assert cached == before, "the cached dictionary itself must not be modified"


def test_a_clean_description_gives_back_exactly_the_same_job() -> None:
    cached = _cached_job(REAL_TEXT)

    once = normalize_job(cached)
    twice = normalize_job(once)

    assert once == twice
    assert once["description"] == REAL_TEXT


def test_the_ai_verdict_stays_on_the_job_until_the_ai_runs_again() -> None:
    cleaned = normalize_job(_cached_job(WALL + LINE_SEPARATOR + REAL_TEXT))

    assert cleaned["ai_suitable"] is True
    assert cleaned["ai_reason"] == "Good fit"
    assert cleaned["ai_key"] == "abc123"


def _key_before_and_after_cleaning(stored_description: str) -> tuple[str, str]:
    """Analysis key of a job as an older scan stored it, and of the same job after normalizing it."""
    as_stored = normalize_job(_cached_job(REAL_TEXT))
    as_stored["description"] = stored_description
    after_cleaning = normalize_job(as_stored)
    return ai_analyzer.analysis_key(as_stored, "profile"), ai_analyzer.analysis_key(after_cleaning, "profile")


def test_the_analysis_key_does_not_change_when_the_description_was_already_clean() -> None:
    before, after = _key_before_and_after_cleaning(REAL_TEXT)

    assert before == after


def test_the_analysis_key_changes_when_the_text_the_model_would_read_really_changes() -> None:
    before, after = _key_before_and_after_cleaning(WALL + LINE_SEPARATOR + REAL_TEXT)

    assert before != after


def test_the_analysis_key_ignores_the_text_after_the_part_the_model_reads() -> None:
    beginning = "Mansione " * 200
    short_version = _cached_job(beginning)
    longer_version = _cached_job(beginning + LINE_SEPARATOR + "Altro testo oltre quello letto dal modello. " * 20)

    assert ai_analyzer.analysis_key(short_version, "profile") == ai_analyzer.analysis_key(longer_version, "profile")


def test_an_old_analysis_is_only_cleared_when_the_ai_is_about_to_run(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "key-in-the-environment")
    monkeypatch.setattr(main, "_AI_ENABLED", False)
    monkeypatch.setattr(main, "_ACTIVE_SOURCES", None)
    monkeypatch.setattr(main, "CACHE_FILE", tmp_path / "jobs_cache.json")
    monkeypatch.setattr(main, "generate_html", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_open_dashboard", lambda *_: None)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("no paid call and no analysis work while the AI is off")

    monkeypatch.setattr(main, "analyze_jobs", forbidden)
    monkeypatch.setattr(ai_analyzer, "_create_openai_client", forbidden)
    job = normalize_job(_cached_job(WALL + LINE_SEPARATOR + REAL_TEXT))

    main._finalize_jobs([job], main.datetime.now())

    assert job["ai_suitable"] is True
    assert job["ai_status"] == "analyzed"
    assert job["ai_key"] == "abc123"

"""A listing the portal still shows was seen, even when the current filters hide it.

The filters decide what the dashboard shows and what is worth a description or an AI
rating. They never decide whether a cached listing is still online.
"""

from datetime import datetime, timedelta

import main
from job_lifecycle import merge_scan
from job_model import normalize_job
from job_pipeline import process_jobs
from preferences import SearchPreferences
from scrapers.site_report import RunReport

NOW = datetime(2026, 11, 10, 9, 0, 0)
LOGISTICS_ONLY = frozenset({"logistics"})
URL = "https://example.ch/jobs/1"


def _raw(title: str = "Sviluppatore Python", url: str = URL, city: str = "Chiasso", **extra: object) -> dict:
    job = {"title": title, "company": "ACME SA", "city": city, "date": "2026-11-01",
           "url": url, "source": "jobs.ch"}
    job.update(extra)
    return job


def _cached(days_ago: int = 3, **extra: object) -> dict:
    seen = (NOW - timedelta(days=days_ago)).isoformat()
    job = normalize_job(_raw(**extra))
    job.update({"first_seen": seen, "last_seen": seen, "last_verified": seen, "status": "active"})
    return job


def _scan(raw_jobs: list[dict], previous: list[dict], preferences: SearchPreferences) -> list[dict]:
    result = process_jobs(raw_jobs, preferences)
    jobs, _counts = merge_scan(previous, result.jobs, {"jobs.ch": "ok"}, preferences, NOW,
                               seen_but_hidden=result.hidden_jobs)
    return jobs


def test_the_pipeline_keeps_what_was_seen_apart_from_what_is_wanted() -> None:
    preferences = SearchPreferences(categories=LOGISTICS_ONLY)

    result = process_jobs([_raw(), _raw("Magazziniere", "https://example.ch/jobs/2")], preferences)

    assert [job["title"] for job in result.jobs] == ["Magazziniere"]
    assert [job["title"] for job in result.hidden_jobs] == ["Sviluppatore Python"]


def test_an_unsafe_link_is_neither_wanted_nor_seen() -> None:
    result = process_jobs([_raw(url="javascript:alert(1)")], SearchPreferences())

    assert result.jobs == []
    assert result.hidden_jobs == []


def test_a_cached_job_found_again_is_not_expired_because_the_category_filter_hides_it() -> None:
    previous = _cached(description="Sviluppo di servizi in Python.", ai_suitable=True, ai_key="abc")

    jobs = _scan([_raw()], [previous], SearchPreferences(categories=LOGISTICS_ONLY))

    assert len(jobs) == 1
    assert jobs[0]["status"] == "active"
    assert jobs[0]["status_reason"] == ""
    assert jobs[0]["last_seen"] == NOW.isoformat()
    assert jobs[0]["first_seen"] == previous["first_seen"]
    assert jobs[0]["description"] == "Sviluppo di servizi in Python."
    assert jobs[0]["ai_key"] == "abc"


def test_the_same_holds_for_seniority_contract_area_and_remote_filters() -> None:
    hiding_preferences = [
        SearchPreferences(seniority_levels=frozenset({"junior"})),
        SearchPreferences(contract_types=frozenset({"internship"})),
    ]
    senior = {"title": "Senior Python Developer", "description": "Contratto a tempo indeterminato."}
    for preferences in hiding_preferences:
        jobs = _scan([_raw(**senior)], [_cached(**senior)], preferences)
        assert [job["status"] for job in jobs] == ["active"], preferences

    far_away = {"city": "Roma"}
    jobs = _scan([_raw(**far_away)], [_cached(**far_away)], SearchPreferences())
    assert [job["status"] for job in jobs] == ["active"]


def test_a_cached_job_that_is_really_missing_still_follows_the_expiry_policy() -> None:
    other_listing = _raw("Magazziniere", "https://example.ch/jobs/2")

    jobs = _scan([other_listing], [_cached()], SearchPreferences(categories=LOGISTICS_ONLY))

    statuses = {job["title"]: job["status"] for job in jobs}
    assert statuses == {"Magazziniere": "active", "Sviluppatore Python": "possibly_expired"}


def test_a_hidden_listing_that_was_never_cached_does_not_enter_the_cache() -> None:
    jobs = _scan([_raw()], [], SearchPreferences(categories=LOGISTICS_ONLY))

    assert jobs == []


def test_retention_still_drops_old_jobs_that_were_not_seen() -> None:
    ancient = _cached(days_ago=90, url="https://example.ch/jobs/old")

    jobs = _scan([_raw()], [ancient], SearchPreferences(categories=LOGISTICS_ONLY))

    assert jobs == []


def _main_with_cache(monkeypatch, tmp_path, cached_jobs: list[dict], preferences: SearchPreferences) -> None:
    cache = tmp_path / "jobs_cache.json"
    main.cache_store.save_jobs(cache, cached_jobs)
    report = RunReport()
    report.finish("jobs.ch", 1, 1.0)
    monkeypatch.setattr(main, "CACHE_FILE", cache)
    monkeypatch.setattr(main, "run_report", report)
    monkeypatch.setattr(main, "_PREFERENCES", preferences)
    monkeypatch.setattr(main, "_ACTIVE_SOURCES", None)


def test_a_full_scan_keeps_a_hidden_cached_job_active_and_out_of_the_dashboard(monkeypatch, tmp_path) -> None:
    _main_with_cache(monkeypatch, tmp_path, [_cached()], SearchPreferences(categories=LOGISTICS_ONLY))

    jobs = main._build_job_list([_raw()], False)

    assert [job["status"] for job in jobs] == ["active"]
    assert main._visible_jobs(jobs) == []


def test_no_page_is_opened_for_a_listing_the_filters_hide(monkeypatch, tmp_path) -> None:
    _main_with_cache(monkeypatch, tmp_path, [_cached()], SearchPreferences(categories=LOGISTICS_ONLY))
    opened: list[str] = []

    def record_description_page(_context, url):
        opened.append(url)
        return {"description": "", "email": ""}

    def record_verification_page(_context, url):
        opened.append(url)
        return "available"

    monkeypatch.setattr(main, "fetch_description", record_description_page)
    monkeypatch.setattr(main, "check_listing", record_verification_page)
    jobs = main._build_job_list([_raw()], False)
    assert jobs[0].get("description", "") == ""

    main._download_descriptions(None, jobs)
    main._verify_possibly_expired(None, jobs)

    assert opened == []


def test_only_visible_possibly_expired_jobs_use_the_verification_budget(monkeypatch, tmp_path) -> None:
    hidden = _cached(url="https://example.ch/jobs/hidden")
    wanted = _cached(title="Magazziniere", url="https://example.ch/jobs/wanted")
    _main_with_cache(monkeypatch, tmp_path, [hidden, wanted], SearchPreferences(categories=LOGISTICS_ONLY))
    checked: list[str] = []

    def record_verification_page(_context, url):
        checked.append(url)
        return "available"

    monkeypatch.setattr(main, "check_listing", record_verification_page)
    jobs = main._build_job_list([], False)
    assert {job["status"] for job in jobs} == {"possibly_expired"}

    main._verify_possibly_expired(None, jobs)

    assert checked == ["https://example.ch/jobs/wanted"]


# ---- links to the same job on other portals


def _cached_on_two_portals() -> dict:
    job = _cached()
    job["sources"] = [{"source": "jobs.ch", "url": URL},
                      {"source": "linkedin.ch", "url": "https://www.linkedin.com/jobs/view/9"}]
    return job


def _merge_with_outcomes(outcomes: dict[str, str]) -> list[dict]:
    result = process_jobs([_raw()], SearchPreferences())
    jobs, _counts = merge_scan([_cached_on_two_portals()], result.jobs, outcomes, SearchPreferences(), NOW,
                               seen_but_hidden=result.hidden_jobs)
    return jobs


def test_the_link_on_a_portal_that_was_blocked_or_not_scanned_is_kept() -> None:
    for outcomes in ({"jobs.ch": "ok", "linkedin.ch": "blocked"}, {"jobs.ch": "ok"}):
        jobs = _merge_with_outcomes(outcomes)

        assert len(jobs) == 1
        assert [reference["source"] for reference in jobs[0]["sources"]] == ["jobs.ch", "linkedin.ch"], outcomes


def test_the_link_on_a_portal_that_no_longer_lists_the_job_is_dropped() -> None:
    jobs = _merge_with_outcomes({"jobs.ch": "ok", "linkedin.ch": "ok"})

    assert [reference["source"] for reference in jobs[0]["sources"]] == ["jobs.ch"]

"""Freshness: first/last seen, blocked portals, expiry policy and verification."""

import json
from datetime import datetime, timedelta

import pytest

from cache_store import CacheFormatError, load_jobs, needs_migration, save_jobs
from job_lifecycle import apply_verification, jobs_to_verify, merge_scan
from job_model import normalize_job
from job_pipeline import process_jobs
from preferences import SearchPreferences

NOW = datetime(2026, 11, 8, 12, 0, 0)


def _job(number: int = 1, source: str = "jobs.ch", **extra: object) -> dict:
    base = {
        "title": f"Sviluppatore Python {number}",
        "company": f"ACME {number} SA",
        "city": "Chiasso",
        "date": "2026-11-01",
        "url": f"https://example.ch/{source}/{number}",
        "source": source,
    }
    base.update(extra)
    return base


def _cached(number: int = 1, source: str = "jobs.ch", days_ago: int = 0, **extra: object) -> dict:
    seen = (NOW - timedelta(days=days_ago)).isoformat()
    job = normalize_job(_job(number, source, **extra))
    job.update({"first_seen": seen, "last_seen": seen, "last_verified": seen, "status": "active"})
    return job


def _scan(current: list[dict], previous: list[dict], outcomes: dict[str, str], **preference_changes: object):
    preferences = SearchPreferences(**preference_changes)
    new_jobs = process_jobs(current, preferences).jobs
    return merge_scan(previous, new_jobs, outcomes, preferences, NOW)


def _by_url(jobs: list[dict]) -> dict[str, dict]:
    return {job["url"]: job for job in jobs}


def test_new_job_gets_first_and_last_seen_and_active_status() -> None:
    jobs, counts = _scan([_job()], [], {"jobs.ch": "ok"})
    assert jobs[0]["first_seen"] == jobs[0]["last_seen"] == NOW.isoformat()
    assert jobs[0]["status"] == "active"
    assert counts == {"active": 1}


def test_rescan_keeps_the_original_first_seen_and_carries_over_analysis() -> None:
    previous = _cached(days_ago=3, description="Full text", ai_suitable=True, ai_key="abc")
    jobs, _ = _scan([_job()], [previous], {"jobs.ch": "ok"})
    assert jobs[0]["first_seen"] == previous["first_seen"]
    assert jobs[0]["last_seen"] == NOW.isoformat()
    assert jobs[0]["description"] == "Full text"
    assert jobs[0]["ai_key"] == "abc"


def test_blocked_source_keeps_its_jobs_and_marks_them_cached() -> None:
    previous = _cached(days_ago=1)
    jobs, counts = _scan([], [previous], {"jobs.ch": "blocked"})
    assert len(jobs) == 1
    assert jobs[0]["status"] == "cached_source_unavailable"
    assert "blocked" in jobs[0]["status_reason"]
    assert jobs[0]["last_seen"] == previous["last_seen"]
    assert counts == {"cached_source_unavailable": 1}


def test_source_not_scanned_in_this_run_keeps_its_jobs() -> None:
    jobs, _ = _scan([], [_cached(days_ago=1)], {})
    assert jobs[0]["status"] == "cached_source_unavailable"
    assert "not scanned" in jobs[0]["status_reason"]


def test_missing_from_a_complete_scan_is_possibly_expired_not_deleted() -> None:
    jobs, _ = _scan([], [_cached(days_ago=1)], {"jobs.ch": "ok"})
    assert jobs[0]["status"] == "possibly_expired"


def test_old_unseen_jobs_become_possibly_expired_then_are_dropped() -> None:
    expiry_days, retention_days = 14, 60
    stale = _cached(1, days_ago=20)
    ancient = _cached(2, days_ago=61)
    jobs, _ = _scan([], [stale, ancient], {"jobs.ch": "blocked"}, expiry_days=expiry_days,
                    retention_days=retention_days)
    assert len(jobs) == 1
    assert jobs[0]["status"] == "possibly_expired"
    assert "20 days" in jobs[0]["status_reason"]


def test_expiry_policy_is_configurable() -> None:
    previous = _cached(days_ago=20)
    relaxed, _ = _scan([], [previous], {"jobs.ch": "blocked"}, expiry_days=30)
    strict, _ = _scan([], [previous], {"jobs.ch": "blocked"}, expiry_days=10)
    assert relaxed[0]["status"] == "cached_source_unavailable"
    assert strict[0]["status"] == "possibly_expired"


def test_legacy_jobs_without_dates_start_tracking_without_an_invented_first_seen() -> None:
    legacy = normalize_job(_job())
    jobs, _ = _scan([], [legacy], {"jobs.ch": "blocked"})
    assert jobs[0]["first_seen"] == ""
    assert jobs[0]["last_seen"] == ""
    assert jobs[0]["tracked_since"] == NOW.isoformat()
    assert jobs[0]["status"] == "cached_source_unavailable"


def test_same_job_found_on_another_portal_is_merged_with_the_cached_copy() -> None:
    cached_copy = _cached(1, "jobs.ch", days_ago=2)
    other_portal = _job(1, "jobscout24.ch", url="https://other.ch/9")
    jobs, _ = _scan([other_portal], [cached_copy], {"jobs.ch": "blocked", "jobscout24.ch": "ok"})
    assert len(jobs) == 1
    assert jobs[0]["status"] == "active"
    assert {ref["source"] for ref in jobs[0]["sources"]} == {"jobs.ch", "jobscout24.ch"}
    assert jobs[0]["first_seen"] == cached_copy["first_seen"]


def test_verification_updates_the_status() -> None:
    job = _cached(days_ago=20)
    jobs, _ = _scan([], [job], {"jobs.ch": "ok"})
    assert [candidate["url"] for candidate in jobs_to_verify(jobs, 5)] == [job["url"]]
    apply_verification(jobs[0], "gone", NOW)
    assert jobs[0]["status"] == "gone"
    apply_verification(jobs[0], "available", NOW)
    assert jobs[0]["status"] == "online_verified"
    apply_verification(jobs[0], "unknown", NOW)
    assert jobs[0]["status"] == "online_verified"


def test_verification_limit_is_respected() -> None:
    previous = [_cached(number, days_ago=20) for number in range(1, 6)]
    jobs, _ = _scan([], previous, {"jobs.ch": "ok"})
    assert len(jobs_to_verify(jobs, 3)) == 3


def test_cache_save_is_atomic_and_keeps_backups(tmp_path) -> None:
    cache_file = tmp_path / "jobs_cache.json"
    legacy_jobs = [_job()]
    cache_file.write_text(json.dumps(legacy_jobs), encoding="utf-8")
    assert needs_migration(cache_file) is True
    save_jobs(cache_file, [normalize_job(job) for job in legacy_jobs])
    assert json.loads((tmp_path / "jobs_cache.json.pre-v2.bak").read_text(encoding="utf-8")) == legacy_jobs
    assert needs_migration(cache_file) is False
    save_jobs(cache_file, [])
    assert (tmp_path / "jobs_cache.json.bak").exists()
    assert list(tmp_path.glob(".jobs-cache-*.tmp")) == []


def test_load_brings_old_jobs_to_the_normalized_shape(tmp_path) -> None:
    cache_file = tmp_path / "jobs_cache.json"
    cache_file.write_text(json.dumps([_job(llm_adatto=True)]), encoding="utf-8")
    loaded = load_jobs(cache_file)
    assert loaded[0]["country"] == "CH"
    assert loaded[0]["sources"]
    assert loaded[0]["ai_suitable"] is True


def test_corrupt_cache_is_reported_and_left_untouched(tmp_path) -> None:
    cache_file = tmp_path / "jobs_cache.json"
    cache_file.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(CacheFormatError):
        load_jobs(cache_file)
    assert json.loads(cache_file.read_text(encoding="utf-8")) == {"not": "a list"}

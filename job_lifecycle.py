"""Keep track of when a job was first and last seen, and how far to trust old listings.

A portal that is blocked or down never deletes the jobs we already have. At the same
time, an old listing is never shown as if it had just been published: every job carries
its first sighting, its last sighting and a status.

Fields on each job:
    first_seen, last_seen, last_verified    ISO timestamps; "" when not known
    tracked_since                           date tracking started for jobs cached before it existed
    status, status_reason                   see job_status.py
"""

from datetime import datetime

from job_dedup import deduplicate
from job_filter import normalize_url
from job_status import (
    STATUS_ACTIVE,
    STATUS_CACHED,
    STATUS_GONE,
    STATUS_ONLINE_VERIFIED,
    STATUS_POSSIBLY_EXPIRED,
)
from preferences import SearchPreferences

SOURCE_FULLY_SCANNED = "ok"

# Fields filled in later (descriptions, AI, salary text) that must survive a rescan.
CARRIED_FIELDS = ("description", "email", "salary_text")
CARRIED_PREFIXES = ("ai_",)
CARRIED_LEGACY_FIELDS = ("estimated_gross_salary_chf",)

SECONDS_PER_DAY = 86_400


def merge_scan(
    previous_jobs: list[dict],
    current_jobs: list[dict],
    source_outcomes: dict[str, str],
    preferences: SearchPreferences,
    now: datetime,
) -> tuple[list[dict], dict[str, int]]:
    """Combine the cache with a new scan. Returns (jobs, counts by status)."""
    now_text = now.replace(microsecond=0).isoformat()
    previous_by_url = _index_by_url(previous_jobs)
    matched_ids: set[int] = set()
    merged_jobs = [_mark_seen(job, previous_by_url, matched_ids, now_text) for job in current_jobs]
    for previous_job in previous_jobs:
        if id(previous_job) in matched_ids:
            continue
        kept_job = _age_unmatched_job(previous_job, source_outcomes, preferences, now)
        if kept_job is not None:
            merged_jobs.append(kept_job)
    unique_jobs, _duplicates = deduplicate(merged_jobs)
    return unique_jobs, _count_statuses(unique_jobs)


def _index_by_url(jobs: list[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for job in jobs:
        for reference in _references(job):
            index[normalize_url(reference["url"])] = job
    return index


def _references(job: dict) -> list[dict]:
    references = job.get("sources")
    if isinstance(references, list) and references:
        return [ref for ref in references if isinstance(ref, dict) and ref.get("url")]
    if job.get("url"):
        return [{"source": job.get("source", ""), "url": job["url"]}]
    return []


def _mark_seen(job: dict, previous_by_url: dict, matched_ids: set[int], now_text: str) -> dict:
    previous_job = _find_previous(job, previous_by_url)
    first_seen = now_text
    if previous_job is not None:
        matched_ids.add(id(previous_job))
        _carry_over(previous_job, job)
        first_seen = previous_job.get("first_seen") or now_text
    job["first_seen"] = first_seen
    job["last_seen"] = now_text
    job["last_verified"] = now_text
    job["status"] = STATUS_ACTIVE
    job["status_reason"] = ""
    return job


def _find_previous(job: dict, previous_by_url: dict) -> dict | None:
    for reference in _references(job):
        previous_job = previous_by_url.get(normalize_url(reference["url"]))
        if previous_job is not None:
            return previous_job
    return None


def _carry_over(previous_job: dict, job: dict) -> None:
    """Reuse what was already downloaded or analysed; never overwrite fresh data."""
    for field_name in CARRIED_FIELDS:
        if previous_job.get(field_name) and not job.get(field_name):
            job[field_name] = previous_job[field_name]
    for field_name, value in previous_job.items():
        if field_name.startswith(CARRIED_PREFIXES) or field_name in CARRIED_LEGACY_FIELDS:
            job.setdefault(field_name, value)


def _age_unmatched_job(
    job: dict,
    source_outcomes: dict[str, str],
    preferences: SearchPreferences,
    now: datetime,
) -> dict | None:
    """Decide the state of a cached job that the latest scan did not return."""
    job = dict(job)
    _start_tracking_if_needed(job, now)
    age_days = _age_in_days(job, now)
    if age_days > preferences.retention_days:
        return None
    if job.get("status") == STATUS_GONE:
        return job
    if age_days > preferences.expiry_days:
        _set_status(job, STATUS_POSSIBLY_EXPIRED, f"not seen for {age_days} days")
        return job
    _set_status_from_sources(job, source_outcomes)
    return job


def _start_tracking_if_needed(job: dict, now: datetime) -> None:
    """Jobs cached before tracking existed get a start date, not an invented first sighting."""
    has_clock = job.get("last_seen") or job.get("last_verified") or job.get("tracked_since")
    if not has_clock:
        job["tracked_since"] = now.replace(microsecond=0).isoformat()
        job.setdefault("first_seen", "")
        job.setdefault("last_seen", "")
        job.setdefault("last_verified", "")


def _age_in_days(job: dict, now: datetime) -> int:
    reference_text = job.get("last_verified") or job.get("last_seen") or job.get("tracked_since") or ""
    try:
        reference = datetime.fromisoformat(reference_text)
    except ValueError:
        return 0
    seconds = (now - reference).total_seconds()
    return max(0, int(seconds // SECONDS_PER_DAY))


def _set_status_from_sources(job: dict, source_outcomes: dict[str, str]) -> None:
    sources = [ref.get("source", "") for ref in _references(job)] or [str(job.get("source") or "")]
    outcomes = [source_outcomes.get(source) for source in sources]
    if all(outcome == SOURCE_FULLY_SCANNED for outcome in outcomes):
        _set_status(job, STATUS_POSSIBLY_EXPIRED, "not in the latest complete scan of its source")
        return
    _set_status(job, STATUS_CACHED, _unavailable_reason(sources, outcomes))


def _unavailable_reason(sources: list[str], outcomes: list[str | None]) -> str:
    for source, outcome in zip(sources, outcomes):
        if outcome is None:
            return f"{source} was not scanned in this run"
        if outcome != SOURCE_FULLY_SCANNED:
            return f"{source} could not be read completely ({outcome})"
    return ""


def _set_status(job: dict, status: str, reason: str) -> None:
    job["status"] = status
    job["status_reason"] = reason


def apply_verification(job: dict, verdict: str, now: datetime) -> None:
    """Record the result of opening the listing page: 'available', 'gone' or 'unknown'."""
    now_text = now.replace(microsecond=0).isoformat()
    if verdict == "gone":
        _set_status(job, STATUS_GONE, "the portal no longer serves this listing")
        job["last_verified"] = now_text
    if verdict == "available":
        _set_status(job, STATUS_ONLINE_VERIFIED, "the listing page is still online")
        job["last_verified"] = now_text


def jobs_to_verify(jobs: list[dict], limit: int) -> list[dict]:
    """Possibly-expired jobs worth a page check, oldest check first, at most `limit`."""
    candidates = [job for job in jobs if job.get("status") == STATUS_POSSIBLY_EXPIRED]
    candidates.sort(key=lambda job: job.get("last_verified") or "")
    return candidates[:limit]


def _count_statuses(jobs: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in jobs:
        status = str(job.get("status") or "")
        counts[status] = counts.get(status, 0) + 1
    return counts

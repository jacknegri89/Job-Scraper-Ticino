"""Merge the same job seen on several portals, without merging different jobs.

Rules, in order:
1. The same canonical URL is the same job.
2. The same company, place and a near-identical title on a DIFFERENT portal is the same
   job. Two listings on the same portal stay separate: they have different links and a
   company can really open several identical positions.
3. Listings without a company, or from staffing agencies, are never merged by content.

The result does not depend on the order of the input.
"""

import re
from difflib import SequenceMatcher

from job_filter import AGENCY_SOURCES, normalize_url
from job_status import STATUS_PRECEDENCE

TITLE_SIMILARITY_THRESHOLD = 0.92
_ANONYMOUS_COMPANIES = ("confidenziale", "confidential", "riservat", "anonim", "vertraulich")
_ONLY_WORD_CHARACTERS = re.compile(r"\W+")
# Fields copied from a duplicate when the main listing does not have them.
_FILL_FIELDS = ("description", "email", "salary_text", "company")


def deduplicate(jobs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (unique jobs with merged sources, the duplicate listings that were merged)."""
    unique_jobs: list[dict] = []
    seen_by_url: dict[str, dict] = {}
    buckets: dict[tuple[str, str], list[dict]] = {}
    duplicate_jobs: list[dict] = []
    for job in _stable_order(jobs):
        existing = _find_existing(job, seen_by_url, buckets)
        if existing is None:
            _register(job, unique_jobs, seen_by_url, buckets)
            continue
        _merge_into(existing, job)
        _index_urls(existing, seen_by_url)
        duplicate_jobs.append(job)
    return unique_jobs, duplicate_jobs


def _stable_order(jobs: list[dict]) -> list[dict]:
    """Newest first; ties by source and URL, so the choice of the main listing is stable."""
    by_source_and_url = sorted(jobs, key=lambda job: (str(job.get("source") or ""), str(job.get("url") or "")))
    return sorted(by_source_and_url, key=lambda job: job.get("published") or "", reverse=True)


def _find_existing(job: dict, seen_by_url: dict, buckets: dict) -> dict | None:
    for reference in job.get("sources") or []:
        match = seen_by_url.get(normalize_url(str(reference.get("url") or "")))
        if match is not None:
            return match
    if not _can_merge_by_content(job):
        return None
    for candidate in buckets.get(_bucket_key(job), []):
        if _is_cross_portal_duplicate(candidate, job):
            return candidate
    return None


def _can_merge_by_content(job: dict) -> bool:
    company = _compact(str(job.get("company") or ""))
    if not company:
        return False
    if any(marker in company for marker in _ANONYMOUS_COMPANIES):
        return False
    return job.get("source") not in AGENCY_SOURCES


def _is_cross_portal_duplicate(candidate: dict, job: dict) -> bool:
    candidate_sources = {reference.get("source") for reference in candidate.get("sources") or []}
    if job.get("source") in candidate_sources:
        return False
    if not _can_merge_by_content(candidate):
        return False
    first_title = _compact(str(candidate.get("title") or ""))
    second_title = _compact(str(job.get("title") or ""))
    if not first_title or not second_title:
        return False
    return SequenceMatcher(None, first_title, second_title).ratio() >= TITLE_SIMILARITY_THRESHOLD


def _bucket_key(job: dict) -> tuple[str, str]:
    company = _compact(str(job.get("company") or ""))[:25]
    place = _compact(str(job.get("place_name") or job.get("city") or ""))
    return company, place


def _register(job: dict, unique_jobs: list[dict], seen_by_url: dict, buckets: dict) -> None:
    unique_jobs.append(job)
    _index_urls(job, seen_by_url)
    if _can_merge_by_content(job):
        buckets.setdefault(_bucket_key(job), []).append(job)


def _index_urls(job: dict, seen_by_url: dict) -> None:
    for reference in job.get("sources") or []:
        seen_by_url[normalize_url(str(reference.get("url") or ""))] = job


def _merge_into(main_job: dict, duplicate: dict) -> None:
    known_urls = {normalize_url(str(ref.get("url") or "")) for ref in main_job["sources"]}
    for reference in duplicate.get("sources") or []:
        if normalize_url(str(reference.get("url") or "")) not in known_urls:
            main_job["sources"].append(reference)
    for field_name in _FILL_FIELDS:
        if not main_job.get(field_name) and duplicate.get(field_name):
            main_job[field_name] = duplicate[field_name]
    _merge_freshness(main_job, duplicate)


def _merge_freshness(main_job: dict, duplicate: dict) -> None:
    """Earliest first sighting, latest sighting and the most reliable state."""
    first_seen_values = [value for value in (main_job.get("first_seen"), duplicate.get("first_seen")) if value]
    if first_seen_values:
        main_job["first_seen"] = min(first_seen_values)
    for field_name in ("last_seen", "last_verified"):
        latest_values = [value for value in (main_job.get(field_name), duplicate.get(field_name)) if value]
        if latest_values:
            main_job[field_name] = max(latest_values)
    main_rank = STATUS_PRECEDENCE.get(main_job.get("status"), -1)
    duplicate_rank = STATUS_PRECEDENCE.get(duplicate.get("status"), -1)
    if duplicate_rank > main_rank:
        main_job["status"] = duplicate["status"]
        main_job["status_reason"] = duplicate.get("status_reason", "")


def _compact(value: str) -> str:
    return _ONLY_WORD_CHARACTERS.sub("", value).lower()

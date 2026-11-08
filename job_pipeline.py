"""From raw scraper output to the jobs the user wants, with the reason for every exclusion.

Order: normalize, check the link, check the area, check field/seniority/contract
preferences, then merge duplicates across portals.
"""

from collections import Counter
from dataclasses import dataclass, field

import geo
from job_dedup import deduplicate
from job_filter import is_safe_job_url
from job_model import normalize_job
from preferences import SearchPreferences

REASON_INVALID_URL = "invalid_url"
REASON_OUT_OF_AREA = "out_of_area"
REASON_UNCERTAIN_LOCATION = "uncertain_location"
REASON_CATEGORY = "category"
REASON_SENIORITY = "seniority"
REASON_CONTRACT = "contract_type"

AREA_STATUS_FIELD = "area_status"


@dataclass
class SourceStats:
    """Numbers for one source in one scan."""

    collected: int = 0
    valid: int = 0
    duplicates: int = 0
    excluded: Counter = field(default_factory=Counter)


@dataclass
class PipelineResult:
    jobs: list[dict]
    stats: dict[str, SourceStats]


def exclusion_reason(job: dict, preferences: SearchPreferences) -> str:
    """Return why a normalized job is not wanted, or '' when it is."""
    if not is_safe_job_url(job.get("url")):
        return REASON_INVALID_URL
    area_status = geo.classify_area(_location_of(job), preferences.area)
    job[AREA_STATUS_FIELD] = area_status
    if area_status == geo.AREA_OUT:
        return REASON_OUT_OF_AREA
    if area_status == geo.AREA_UNCERTAIN and not preferences.include_uncertain_location:
        return REASON_UNCERTAIN_LOCATION
    return _preference_reason(job, preferences)


def _location_of(job: dict) -> geo.Location:
    """Rebuild the location from the raw text so the area check uses the same rules."""
    return geo.resolve_location(str(job.get("city") or ""), str(job.get("country") or ""))


def _preference_reason(job: dict, preferences: SearchPreferences) -> str:
    if preferences.categories is not None and job.get("category") not in preferences.categories:
        return REASON_CATEGORY
    if preferences.seniority_levels is not None and job.get("seniority") not in preferences.seniority_levels:
        return REASON_SENIORITY
    if preferences.contract_types is not None and job.get("contract_type") not in preferences.contract_types:
        return REASON_CONTRACT
    return ""


def process_jobs(raw_jobs: list[dict], preferences: SearchPreferences) -> PipelineResult:
    """Normalize, filter and de-duplicate jobs; count what happened per source."""
    stats: dict[str, SourceStats] = {}
    wanted_jobs: list[dict] = []
    for raw_job in raw_jobs:
        job = normalize_job(raw_job)
        source_stats = stats.setdefault(str(job.get("source") or "?"), SourceStats())
        source_stats.collected += 1
        reason = exclusion_reason(job, preferences)
        if reason:
            source_stats.excluded[reason] += 1
            continue
        wanted_jobs.append(job)
    unique_jobs, duplicate_jobs = deduplicate(wanted_jobs)
    _count_results(unique_jobs, duplicate_jobs, stats)
    return PipelineResult(jobs=unique_jobs, stats=stats)


def _count_results(unique_jobs: list[dict], duplicate_jobs: list[dict], stats: dict[str, SourceStats]) -> None:
    for job in unique_jobs:
        stats[str(job.get("source") or "?")].valid += 1
    for job in duplicate_jobs:
        stats[str(job.get("source") or "?")].duplicates += 1

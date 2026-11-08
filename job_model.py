"""One normalized shape for jobs coming from different portals.

Raw scraper output keeps working: every missing field is derived from what the portal
gave us, and nothing is invented. Fields that cannot be known stay empty.

Normalized fields added to each job:
    country, region, province, place_name, location_certainty   where the job is
    published                                                    YYYY-MM-DD, or "" if unknown
    canonical_url, sources                                       original links on each portal
    category, seniority, seniority_evidence, contract_type       what kind of job it is
"""

from copy import deepcopy

import geo
from job_classifier import classify_contract, classify_seniority
from job_filter import categorize_job, normalize_url, sort_date

COUNTRY_SWITZERLAND = "CH"
COUNTRY_ITALY = "IT"
COUNTRY_UNKNOWN = ""

_COUNTRY_BY_DOMAIN_SUFFIX = ((".ch", COUNTRY_SWITZERLAND), (".it", COUNTRY_ITALY))
_SOURCE_COUNTRY_OVERRIDES = {"frontaliereticino.ch": COUNTRY_SWITZERLAND}


def source_country(source: str) -> str:
    """Country a portal is about, from its name: 'jobs.ch' is Swiss, 'indeed.it' Italian."""
    name = (source or "").strip().lower()
    if name in _SOURCE_COUNTRY_OVERRIDES:
        return _SOURCE_COUNTRY_OVERRIDES[name]
    for suffix, country in _COUNTRY_BY_DOMAIN_SUFFIX:
        if name.endswith(suffix):
            return country
    return COUNTRY_UNKNOWN


def normalize_job(raw_job: dict) -> dict:
    """Return a copy of the job with the normalized fields filled in."""
    job = deepcopy(raw_job)
    title = str(job.get("title") or "")
    description = str(job.get("description") or "")
    _set_location_fields(job)
    job["published"] = sort_date(job.get("date"))
    job["canonical_url"] = normalize_url(str(job.get("url") or ""))
    job["category"] = categorize_job(title)
    level, evidence = classify_seniority(title, description)
    job["seniority"] = level
    job["seniority_evidence"] = evidence
    job["contract_type"] = classify_contract(title, description)
    job["sources"] = _source_references(job)
    return job


def _set_location_fields(job: dict) -> None:
    default_country = source_country(str(job.get("source") or ""))
    location = geo.resolve_location(str(job.get("city") or ""), default_country)
    place = location.place
    job["location_certainty"] = location.certainty
    job["place_name"] = ""
    job["province"] = ""
    job["region"] = location.region
    job["country"] = default_country
    if place is not None:
        job["place_name"] = place.name
        job["province"] = place.province
        job["region"] = place.region
        job["country"] = place.country


def _source_references(job: dict) -> list[dict]:
    """Keep every portal link the job was seen on; the first one is the main one."""
    existing = job.get("sources")
    if isinstance(existing, list) and existing:
        return _clean_references(existing)
    return _clean_references([{"source": job.get("source", ""), "url": job.get("url", "")}])


def _clean_references(references: list) -> list[dict]:
    seen_urls: set[str] = set()
    cleaned: list[dict] = []
    for reference in references:
        if not isinstance(reference, dict):
            continue
        url = str(reference.get("url") or "")
        source = str(reference.get("source") or "")
        url_key = normalize_url(url)
        if not url or url_key in seen_urls:
            continue
        seen_urls.add(url_key)
        cleaned.append({"source": source, "url": url})
    return cleaned

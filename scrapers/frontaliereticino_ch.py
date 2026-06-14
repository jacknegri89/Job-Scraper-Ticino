"""
Scraper for frontaliereticino.ch, focused on Ticino jobs.

The site exposes a static JSON index on its CDN, updated daily:
https://cdn.frontaliereticino.ch/data/jobs-it-index.json

8,000+ Swiss jobs total, about 680 in Ticino (canton == "TI").
No Playwright needed: a simple HTTP GET is enough.
"""

import json
import urllib.request
from datetime import date

from job_filter import categorize_job

_INDEX_URL = "https://cdn.frontaliereticino.ch/data/jobs-it-index.json"
_JOB_BASE  = "https://frontaliereticino.ch/cerca-lavoro-ticino/"
_HEADERS   = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _parse_date(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return date.today().isoformat()
    if len(raw) >= 10 and raw[4] == "-":
        return raw[:10]
    parts = raw.split("/")
    if len(parts) == 3:
        d, m, y = parts
        if len(y) == 2:
            y = "20" + y
        return f"{y}-{int(m):02d}-{int(d):02d}"
    return date.today().isoformat()


def scrape_frontaliereticino_ch(context: object) -> list[dict[str, str]]:  # context unused: pure HTTP.
    print("  [frontaliereticino.ch] Downloading CDN JSON index...")
    data = _download_index()
    if not data:
        return []
    ticino_jobs = [job for job in data if job.get("canton") == "TI"]
    print(f"  [frontaliereticino.ch] {len(ticino_jobs)} Ticino jobs out of {len(data)} total")
    jobs = [_job_from_item(item) for item in ticino_jobs]
    valid_jobs = [job for job in jobs if job is not None]
    print(f"  [frontaliereticino.ch] {len(valid_jobs)} jobs processed")
    return valid_jobs


def _download_index() -> list[dict[str, str]]:
    try:
        return _read_index_response()
    except Exception as exc:
        print(f"  [frontaliereticino.ch] Download error: {exc}")
        return []


def _read_index_response() -> list[dict[str, str]]:
    request = urllib.request.Request(_INDEX_URL, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _job_from_item(item: dict[str, str]) -> dict[str, str] | None:
    slug = item.get("slug", "")
    title = (item.get("title") or "").strip()
    if not slug or not title:
        return None
    return {
        "title": title,
        "company": (item.get("company") or "").strip(),
        "city": _city_from_item(item),
        "date": _parse_date(item.get("postedDate", "")),
        "url": _job_url(item, slug),
        "category": categorize_job(title),
        "source": "frontaliereticino.ch",
    }


def _city_from_item(item: dict[str, str]) -> str:
    return (item.get("addressLocality") or item.get("location") or "").strip()


def _job_url(item: dict[str, str], slug: str) -> str:
    employer_url = (item.get("url") or "").strip()
    return employer_url if employer_url.startswith("http") else f"{_JOB_BASE}{slug}/"

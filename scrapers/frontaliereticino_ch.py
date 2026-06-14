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
    try:
        req = urllib.request.Request(_INDEX_URL, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [frontaliereticino.ch] Download error: {e}")
        return []

    ticino = [j for j in data if j.get("canton") == "TI"]
    print(f"  [frontaliereticino.ch] {len(ticino)} Ticino jobs out of {len(data)} total")

    jobs = []
    for item in ticino:
        slug  = item.get("slug", "")
        title = (item.get("title") or "").strip()
        if not slug or not title:
            continue

        city = (item.get("addressLocality") or item.get("location") or "").strip()
        # Prefer employer URLs for fetch_description, falling back to ft.ch.
        employer_url = (item.get("url") or "").strip()
        url = employer_url if employer_url.startswith("http") else f"{_JOB_BASE}{slug}/"
        jobs.append({
            "title":    title,
            "company":  (item.get("company") or "").strip(),
            "city":     city,
            "date":     _parse_date(item.get("postedDate", "")),
            "url":      url,
            "category": categorize_job(title),
            "source":   "frontaliereticino.ch",
        })

    print(f"  [frontaliereticino.ch] {len(jobs)} jobs processed")
    return jobs

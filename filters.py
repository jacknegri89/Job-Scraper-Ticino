from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

COMUNI_AMMESSI = {
    "chiasso", "mendrisio", "stabio", "balerna",
    "coldrerio", "morbio inferiore", "novazzano", "riva san vitale",
}

KEYWORDS = {
    "tech": [
        "Junior IT", "Help Desk", "Tecnico informatico",
        "Sviluppatore Junior", "Operaio elettronico", "Cablatore",
    ],
    "logistica": [
        "Magazziniere", "Addetto logistica", "Operaio generico",
        "Ausiliario di produzione", "Preparatore ordini",
    ],
    "pulizie": [
        "Ausiliario di pulizia", "Addetto pulizie", "Pulitore",
    ],
    "retail": [
        "Scaffalista", "Addetto vendita", "Cassiere",
    ],
}


def normalize_city(city_raw: str) -> str:
    if " - " in city_raw:
        return city_raw.split(" - ")[-1].strip().lower()
    return city_raw.strip().lower()


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=False)
    clean = {k: v for k, v in params.items() if not k.startswith("utm_")}
    return urlunparse(parsed._replace(query=urlencode(clean, doseq=True)))


def is_valid_job(job: dict) -> bool:
    city = normalize_city(job.get("city", ""))
    url = job.get("url", "")
    if urlparse(url).netloc.endswith(".it"):
        return False
    return city in COMUNI_AMMESSI


def categorize_job(title: str) -> str:
    title_lower = title.lower()
    for category, keywords in KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in title_lower:
                return category
    return "altro"


def filter_jobs(jobs: list) -> list:
    valid = [j for j in jobs if is_valid_job(j)]
    seen, deduped = set(), []
    for job in valid:
        key = normalize_url(job["url"])
        if key not in seen:
            seen.add(key)
            deduped.append(job)
    return sorted(deduped, key=lambda j: j.get("date", ""), reverse=True)

"""Filtering and normalization helpers for scraped jobs."""

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

ALLOWED_CITIES = {
    "chiasso",
    "mendrisio",
    "stabio",
    "balerna",
    "coldrerio",
    "morbio inferiore",
    "novazzano",
    "riva san vitale",
}

# These are external portal search terms. They stay in Italian because they
# produce better results on Swiss Italian job boards.
SEARCH_TERMS = [
    "operaio",
    "magazziniere",
    "tecnico",
    "addetto",
    "informatico",
    "cablatore",
    "cameriere",
    "commesso",
    "autista",
    "assemblatore",
    "pulizie",
    "logistica",
    "elettricista",
    "produzione",
]

KEYWORDS = {
    "tech": [
        "Junior IT", "Help Desk", "Helpdesk", "IT Support",
        "Tecnico informatico", "Tecnico IT", "Operatore informatico",
        "Sviluppatore Junior", "Sistemista", "Tecnico reti",
        "Network technician", "Tecnico hardware", "Tecnico software",
        "Operaio elettronico", "Cablatore", "Cablaggio",
        "Tecnico elettronico", "Assemblatore elettronico",
        "Montatore elettronico", "Tecnico di laboratorio",
        "IoT", "Raspberry", "Elettrotecnico",
        "Operatore CNC", "Programmatore CNC", "Operatore macchine utensili",
        "Elettricista", "Tecnico elettrico", "Installatore elettrico",
    ],
    "logistics": [
        "Magazziniere", "Addetto logistica", "Operaio generico",
        "Ausiliario di produzione", "Preparatore ordini",
        "Carrellista", "Mulettista", "Operatore logistico",
        "Addetto magazzino", "Addetto al magazzino",
        "Addetto spedizioni", "Addetto ricevimento merci",
        "Movimentatore", "Movimentazione merci",
        "Operatore di magazzino", "Responsabile logistica",
        "Factotum",
    ],
    "production": [
        "Operaio di produzione", "Operaio produzione",
        "Operatore macchine", "Operatore di linea",
        "Addetto alla produzione", "Addetto produzione",
        "Assemblatore", "Montatore", "Montaggio",
        "Operaio specializzato", "Operaio polivalente",
        "Controllo qualita", "Controllo qualita'",
        "Addetto controllo qualita", "Operaio metalmeccanico",
        "Metalmeccanico", "Saldatore", "Saldatura",
    ],
    "food_service": [
        "Cameriere", "Cameriera", "Chef de rang",
        "Barista", "Aiuto cuoco", "Cuoco",
        "Addetto mensa", "Mensa", "Lavapiatti",
        "Runner", "Staff di sala",
        "Addetto ristorazione", "Food & Beverage",
    ],
    "cleaning": [
        "Ausiliario di pulizia", "Addetto pulizie", "Pulitore",
        "Operatore pulizie", "Addetto alle pulizie",
        "Pulizie industriali", "Pulizie civili", "Pulizie uffici",
        "Collaboratore pulizie", "Agente di pulizia",
    ],
    "retail": [
        "Scaffalista", "Addetto vendita", "Cassiere",
        "Commesso", "Commessa", "Addetto cassa",
        "Banconista", "Operatore di vendita",
        "Addetto al banco", "Addetto alla cassa",
        "Sales assistant", "Store assistant",
    ],
    "transport": [
        "Autista", "Autista furgone", "Autista camion",
        "Corriere", "Consegne", "Autista di distribuzione",
        "Autista patente B", "Autista patente C",
        "Fattorino", "Driver",
    ],
}

AGENCY_SOURCES = {
    "randstad.ch",
    "orienta.ch",
    "gigroup.ch",
    "adecco.ch",
    "manpower.ch",
}

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
EU_DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})")


def normalize_city(city_raw: str | None) -> str:
    """Normalize the different city formats returned by job portals."""
    city = city_raw or ""
    if " - " in city:
        city = city.split(" - ")[-1].strip()
    city = re.split(r"[,\(]", city)[0].strip()
    city = re.sub(r"^\d{4,5}\s+", "", city)
    city = re.sub(r"\s+(?:TI|CH)$", "", city, flags=re.IGNORECASE)
    return city.strip().lower()


def normalize_url(url: str) -> str:
    """Remove tracking query parameters before URL comparisons."""
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query, keep_blank_values=False)
    clean_params = {
        key: value
        for key, value in query_params.items()
        if not key.startswith("utm_")
    }
    clean_query = urlencode(sorted(clean_params.items()), doseq=True)
    return urlunparse(parsed_url._replace(query=clean_query))


def is_valid_job(job: dict) -> bool:
    """Return True when a job is in the supported Swiss border area."""
    if _is_italian_portal(job.get("url", "")):
        return False
    return normalize_city(job.get("city", "")) in ALLOWED_CITIES


def categorize_job(title: str) -> str:
    """Assign a broad category from the job title."""
    title_lower = title.lower()
    for category, keywords in KEYWORDS.items():
        if _has_keyword(title_lower, keywords):
            return category
    return "other"


def filter_jobs(jobs: list[dict]) -> list[dict]:
    """Filter, deduplicate, and sort jobs by newest date first."""
    seen_urls: set[str] = set()
    seen_content: set[str] = set()
    deduped_jobs: list[dict] = []
    for job in jobs:
        if is_valid_job(job):
            _add_unique_job(job, seen_urls, seen_content, deduped_jobs)
    return sorted(deduped_jobs, key=_sort_date, reverse=True)


def _has_keyword(title_lower: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in title_lower for keyword in keywords)


def _is_italian_portal(url: str) -> bool:
    return urlparse(url).netloc.endswith(".it")


def _add_unique_job(
    job: dict,
    seen_urls: set[str],
    seen_content: set[str],
    deduped_jobs: list[dict],
) -> None:
    job_url = job.get("url", "")
    if not job_url:
        return
    url_key = normalize_url(job_url)
    content_key = _content_key(job)
    if url_key in seen_urls or content_key in seen_content:
        return
    seen_urls.add(url_key)
    seen_content.add(content_key)
    deduped_jobs.append(job)


def _content_key(job: dict) -> str:
    title_key = _compact(job.get("title", ""))[:40]
    company_key = _compact(job.get("company", ""))[:25]
    city_key = normalize_city(job.get("city", ""))
    if job.get("source") in AGENCY_SOURCES:
        url_tail = _compact(job.get("url", ""))[-18:]
        return f"{title_key}|{company_key}|{city_key}|{url_tail}"
    return f"{title_key}|{company_key}|{city_key}"


def _compact(value: str) -> str:
    return re.sub(r"\W+", "", value).lower()


def _sort_date(job: dict) -> str:
    """Convert supported date formats to YYYY-MM-DD for sorting."""
    date_text = job.get("date", "").strip()
    if ISO_DATE.match(date_text):
        return date_text[:10]
    match = EU_DATE.match(date_text)
    if match:
        return f"{match.group(3)}-{int(match.group(2)):02d}-{int(match.group(1)):02d}"
    return ""

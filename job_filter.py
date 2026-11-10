"""Search terms, field categories, URL safety and date helpers for scraped jobs.

Where a job is, whether it is a duplicate and whether the user wants it is decided in
job_pipeline.py. This module holds the small reusable pieces.
"""

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# These are external portal search terms. They stay in Italian because they
# produce better results on Italian and Swiss Italian job boards.
SEARCH_TERMS = [
    "operaio",
    "magazziniere",
    "tecnico",
    "addetto",
    "informatico",
    "sviluppatore",
    "programmatore",
    "sistemista",
    "developer",
    "software engineer",
    "devops",
    "data scientist",
    "machine learning",
    "intelligenza artificiale",
    "cablatore",
    "cameriere",
    "commesso",
    "autista",
    "assemblatore",
    "pulizie",
    "logistica",
    "elettricista",
    "produzione",
    "manutentore",
    "montatore",
    "aiuto cucina",
    "help desk",
    "supporto IT",
    "lagerist",
    "elektriker",
]

CATEGORY_TECH = "tech"
CATEGORY_TECHNICAL = "technical"
CATEGORY_OTHER = "other"

KEYWORDS = {
    # Software, systems, support and AI/data roles.
    CATEGORY_TECH: [
        "Junior IT", "Help Desk", "Helpdesk", "Service Desk", "IT Support", "Supporto IT",
        "Tecnico informatico", "Tecnico IT", "Operatore informatico", "Informatico",
        "Sviluppatore", "Developer", "Programmatore", "Software Engineer", "Software Developer",
        "Full Stack", "Fullstack", "Frontend", "Front-end", "Backend", "Back-end",
        "Web Developer", "Analista programmatore", "Analista funzionale",
        "Sistemista", "System Administrator", "Sysadmin", "Amministratore di sistema",
        "DevOps", "Cloud Engineer", "Network Engineer", "Network technician", "Tecnico reti",
        "Tecnico hardware", "Tecnico software", "Security Engineer", "Cybersecurity",
        "Sicurezza informatica", "Database Administrator", "DBA", "QA Engineer", "Tester",
        "Data Scientist", "Data Engineer", "Data Analyst", "Machine Learning", "AI Engineer",
        "Intelligenza artificiale", "Artificial Intelligence", "Python", "Java", "C#", ".NET",
        "Sviluppo software", "IoT", "Raspberry",
    ],
    # Electronics, electrical and machining roles that used to sit under "tech".
    CATEGORY_TECHNICAL: [
        "Programmatore PLC", "Sviluppatore PLC", "Tecnico PLC",
        "Operaio elettronico", "Cablatore", "Cablaggio",
        "Tecnico elettronico", "Assemblatore elettronico",
        "Montatore elettronico", "Tecnico di laboratorio",
        "Elettrotecnico",
        "Programmatore CNC", "Programmatore macchine", "Operatore CNC", "Controllo numerico",
        "Operatore macchine utensili",
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
        "Tornitore", "Fresatore", "Meccanico",
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

ALL_CATEGORIES = tuple(KEYWORDS) + (CATEGORY_OTHER,)

AGENCY_SOURCES = {
    "randstad.ch",
    "orienta.ch",
    "gigroup.ch",
    "adecco.ch",
    "manpower.ch",
    "randstad.it",
    "gigroup.it",
    "adecco.it",
    "manpower.it",
}

TRACKING_PARAMETERS = frozenset({
    "gclid", "fbclid", "msclkid", "ref", "refid", "trk", "trackingid", "tracking", "src", "source",
})
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
EU_DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})")
DEFAULT_PORTS = {"http": 80, "https": 443}


def _keyword_pattern(keyword: str) -> re.Pattern:
    """Match a keyword only as a whole word, so 'AI' does not match 'assistant'."""
    return re.compile(r"(?<!\w)" + re.escape(keyword.lower()) + r"(?!\w)")


_CATEGORY_PATTERNS = {
    category: [_keyword_pattern(keyword) for keyword in keywords]
    for category, keywords in KEYWORDS.items()
}
_CATEGORY_PATTERNS["tech"].append(re.compile(r"(?<!\w)ai(?!\w)"))


# "Business Developer", "Product Developer" (fashion), "Venditore IA" and similar are sales,
# product or fashion roles that only share a word with software jobs.
_NOT_SOFTWARE = re.compile(
    r"business develop|sviluppo commerciale|sviluppatore commerciale|sviluppo business"
    r"|product develop|sviluppo prodotto|apparel|swimwear|nightwear|footwear|knitwear|textile|tessil|abbigliamento"
    r"|real estate|property develop|immobiliar"
    r"|venditor|vendita|(?<!\w)sales(?!\w)|account manager|recruiter|talent acquisition"
)


# Machining and electrical titles are checked before software ones: "Programmatore CNC"
# is a machinist, not a developer.
_CATEGORY_ORDER = (CATEGORY_TECHNICAL, *(name for name in KEYWORDS if name != CATEGORY_TECHNICAL))


# "Help Desk" next to "Customer Service" is usually a call-centre role, not IT support.
_CUSTOMER_SERVICE = re.compile(
    r"customer service|customer care|customer support|call cent|contact cent|servizio clienti|assistenza clienti"
)

# Words that, together, show that a "help desk" listing is about computers and not about customers.
_IT_SUPPORT_MARKERS = (
    "it support", "supporto it", "supporto informatico", "assistenza informatica", "assistenza tecnica informatica",
    "help desk it", "helpdesk it", "service desk it", "ticketing", "active directory", "windows", "linux",
    "sistemi operativi", "hardware", "troubleshooting", "microsoft 365", "office 365", "vpn",
    "incident management", "itil",
)
MIN_IT_SUPPORT_MARKERS = 2


def categorize_job(title: str, description: str = "") -> str:
    """Assign a broad category from the job title, and from the description when the title is ambiguous."""
    category = _category_from_title(title)
    if category == CATEGORY_TECH and _is_customer_service_title(title) and not _confirms_it_support(description):
        return CATEGORY_OTHER
    return category


def category_awaits_description(title: str, description: str = "") -> bool:
    """True while the category could still change once the description is known."""
    if description:
        return False
    return _category_from_title(title) == CATEGORY_TECH and _is_customer_service_title(title)


def _is_customer_service_title(title: str) -> bool:
    return bool(_CUSTOMER_SERVICE.search((title or "").lower()))


def _confirms_it_support(description: str) -> bool:
    lowered = (description or "").lower()
    found = {marker for marker in _IT_SUPPORT_MARKERS if _keyword_pattern(marker).search(lowered)}
    return len(found) >= MIN_IT_SUPPORT_MARKERS


def _category_from_title(title: str) -> str:
    title_lower = (title or "").lower()
    for category in _CATEGORY_ORDER:
        if category == CATEGORY_TECH and _NOT_SOFTWARE.search(title_lower):
            continue
        if any(pattern.search(title_lower) for pattern in _CATEGORY_PATTERNS[category]):
            return category
    return CATEGORY_OTHER


def normalize_url(url: str) -> str:
    """Canonical form of a URL: no tracking parameters, fragment or default port."""
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query, keep_blank_values=False)
    clean_params = {
        key: value
        for key, value in query_params.items()
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
    }
    clean_query = urlencode(sorted(clean_params.items()), doseq=True)
    host = (parsed_url.hostname or "").lower()
    netloc = host
    if parsed_url.port is not None and parsed_url.port != DEFAULT_PORTS.get(parsed_url.scheme):
        netloc = f"{host}:{parsed_url.port}"
    path = parsed_url.path.rstrip("/") or parsed_url.path
    return urlunparse((parsed_url.scheme.lower(), netloc, path, "", clean_query, ""))


def is_safe_job_url(url: object) -> bool:
    """Accept only plain http(s) URLs with a host and no embedded credentials."""
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        return parsed.username is None and parsed.password is None
    except ValueError:
        return False


def sort_date(date_text: str | None) -> str:
    """Convert supported date formats to YYYY-MM-DD, or '' when the date is unknown."""
    text = (date_text or "").strip()
    if ISO_DATE.match(text):
        return text[:10]
    match = EU_DATE.match(text)
    if match:
        return f"{match.group(3)}-{int(match.group(2)):02d}-{int(match.group(1)):02d}"
    return ""

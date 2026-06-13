import re
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

COMUNI_AMMESSI = {
    "chiasso", "mendrisio", "stabio", "balerna",
    "coldrerio", "morbio inferiore", "novazzano", "riva san vitale",
}

# Termini usati come query di ricerca su jobs.ch.
# Mantieni questa lista CORTA (≤15 voci) — ogni termine = 3 pagine di richieste HTTP.
# Usa termini generici che coprono molti tipi di lavoro.
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

# Usato per CATEGORIZZARE gli annunci (su tutti i portali).
# Può essere più lungo — non genera richieste HTTP aggiuntive.
KEYWORDS = {
    "tech": [
        # Informatica / IT
        "Junior IT", "Help Desk", "Helpdesk", "IT Support",
        "Tecnico informatico", "Tecnico IT", "Operatore informatico",
        "Sviluppatore Junior", "Sistemista", "Tecnico reti",
        "Network technician", "Tecnico hardware", "Tecnico software",
        # Elettronica / hardware
        "Operaio elettronico", "Cablatore", "Cablaggio",
        "Tecnico elettronico", "Assemblatore elettronico",
        "Montatore elettronico", "Tecnico di laboratorio",
        "IoT", "Raspberry", "Elettrotecnico",
        # CNC / automazione
        "Operatore CNC", "Programmatore CNC", "Operatore macchine utensili",
        # Elettricità
        "Elettricista", "Tecnico elettrico", "Installatore elettrico",
    ],
    "logistica": [
        "Magazziniere", "Addetto logistica", "Operaio generico",
        "Ausiliario di produzione", "Preparatore ordini",
        "Carrellista", "Mulettista", "Operatore logistico",
        "Addetto magazzino", "Addetto al magazzino",
        "Addetto spedizioni", "Addetto ricevimento merci",
        "Movimentatore", "Movimentazione merci",
        "Operatore di magazzino", "Responsabile logistica",
        "Factotum",
    ],
    "produzione": [
        "Operaio di produzione", "Operaio produzione",
        "Operatore macchine", "Operatore di linea",
        "Addetto alla produzione", "Addetto produzione",
        "Assemblatore", "Montatore", "Montaggio",
        "Operaio specializzato", "Operaio polivalente",
        "Controllo qualità", "Addetto controllo qualità",
        "Operaio metalmeccanico", "Metalmeccanico",
        "Saldatore", "Saldatura",
    ],
    "ristorazione": [
        "Cameriere", "Cameriera", "Chef de rang",
        "Barista", "Aiuto cuoco", "Cuoco",
        "Addetto mensa", "Mensa", "Lavapiatti",
        "Runner", "Staff di sala",
        "Addetto ristorazione", "Food & Beverage",
    ],
    "pulizie": [
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
    "trasporti": [
        "Autista", "Autista furgone", "Autista camion",
        "Corriere", "Consegne", "Autista di distribuzione",
        "Autista patente B", "Autista patente C",
        "Fattorino", "Driver",
    ],
}


def normalize_city(city_raw: str) -> str:
    if " - " in city_raw:
        city_raw = city_raw.split(" - ")[-1].strip()
    # Strip canton/region suffixes: "Chiasso, TI" → "Chiasso", "Chiasso (TI)" → "Chiasso"
    city_raw = re.split(r'[,\(]', city_raw)[0].strip()
    # CAP svizzero iniziale: "6850 Chiasso" → "Chiasso"
    city_raw = re.sub(r'^\d{4,5}\s+', '', city_raw)
    # Sigla cantone in coda senza virgola: "Chiasso TI" / "Stabio CH" → nome pulito
    city_raw = re.sub(r'\s+(?:TI|CH)$', '', city_raw, flags=re.IGNORECASE)
    return city_raw.strip().lower()


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=False)
    clean = {k: v for k, v in params.items() if not k.startswith("utm_")}
    return urlunparse(parsed._replace(query=urlencode(sorted(clean.items()), doseq=True)))


def _su_portale_italiano(url: str) -> bool:
    """Gli annunci su domini .it sono lavori in Italia, non frontalierato."""
    return urlparse(url).netloc.endswith(".it")


def is_valid_job(job: dict) -> bool:
    """Vero se l'annuncio è in un comune ammesso e non su un portale italiano."""
    if _su_portale_italiano(job.get("url", "")):
        return False
    return normalize_city(job.get("city", "")) in COMUNI_AMMESSI


def categorize_job(title: str) -> str:
    title_lower = title.lower()
    for category, keywords in KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in title_lower:
                return category
    return "altro"


# Agenzie di somministrazione: il nome azienda è sempre identico,
# quindi title+company+city deduplica per errore posizioni genuinamente diverse.
# Per queste sorgenti si aggiunge un frammento dell'URL per distinguerle.
_AGENZIE = {"randstad.ch", "orienta.ch", "gigroup.ch", "adecco.ch", "manpower.ch"}


def _content_key(job: dict) -> str:
    """Chiave per dedup cross-portale (stesso annuncio su jobs.ch e jobscout24.ch)."""
    t    = re.sub(r'\W+', '', job.get("title",   "")).lower()[:40]
    c    = re.sub(r'\W+', '', job.get("company", "")).lower()[:25]
    city = normalize_city(job.get("city", ""))
    # Per agenzie: aggiungi i ~20 caratteri finali dell'URL (slug/UUID univoco)
    if job.get("source") in _AGENZIE:
        url_tail = re.sub(r'\W+', '', job.get("url", ""))[-18:]
        return f"{t}|{c}|{city}|{url_tail}"
    return f"{t}|{c}|{city}"


def filter_jobs(jobs: list) -> list:
    valid = [j for j in jobs if is_valid_job(j)]
    seen_url     = set()
    seen_content = set()
    deduped      = []
    for job in valid:
        url = job.get("url", "")
        if not url:
            continue
        url_key     = normalize_url(url)
        content_key = _content_key(job)
        if url_key in seen_url or content_key in seen_content:
            continue
        seen_url.add(url_key)
        seen_content.add(content_key)
        deduped.append(job)
    return sorted(deduped, key=_sort_date, reverse=True)


_ISO_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}')
_EU_DATE  = re.compile(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})')


def _sort_date(job: dict) -> str:
    """
    Chiave di ordinamento tollerante: le date sono in formati misti tra portali.
    ISO (YYYY-MM-DD) ordina correttamente; DD.MM.YYYY viene convertito;
    tutto il resto (testo grezzo) finisce in fondo.
    """
    d = job.get("date", "").strip()
    if _ISO_DATE.match(d):
        return d[:10]
    m = _EU_DATE.match(d)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return ""

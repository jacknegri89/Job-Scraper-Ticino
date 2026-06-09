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
        url = job.get("url", "")
        if not url:
            continue
        key = normalize_url(url)
        if key not in seen:
            seen.add(key)
            deduped.append(job)
    return sorted(deduped, key=lambda j: j.get("date", ""), reverse=True)

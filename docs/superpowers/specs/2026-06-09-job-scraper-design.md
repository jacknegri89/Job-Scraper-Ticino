# Job Scraper Frontaliero — Design Spec
**Data:** 2026-06-09  
**Autore:** Giacomo Negri  
**Stato:** Approvato

---

## Contesto

Giacomo Negri, 20 anni, diploma IT giugno 2026, risiede a Barlassina (MB) — comune entro i 20 km dalla frontiera svizzera. Cerca lavoro frontaliero in Svizzera, limitato ai comuni del Mendrisiotto raggiungibili in 30-40 minuti d'auto. Obiettivo: automatizzare la raccolta quotidiana di annunci evitando la navigazione manuale su più siti.

---

## Struttura File

```
Lavoro/
├── scraper.py                          ← entry point
├── scrapers/
│   ├── __init__.py
│   ├── jobs_ch.py                      ← scraper jobs.ch
│   └── carriera_ch.py                  ← scraper carriera.ch
├── filters.py                          ← whitelist comuni + deduplicazione
├── html_generator.py                   ← genera index.html
├── requirements.txt
├── setup_task_scheduler.bat            ← configura Windows Task Scheduler
├── COME_AVVIARE.md                     ← istruzioni per l'utente
├── profile/                            ← contesto browser persistente (cookies)
└── index.html                          ← output generato automaticamente
```

---

## Modello Dati

Ogni annuncio valido è rappresentato come dict Python:

```python
{
    "title":    str,   # Titolo della posizione
    "company":  str,   # Azienda o agenzia interinale
    "city":     str,   # Comune svizzero (es. "Chiasso")
    "date":     str,   # Data pubblicazione ISO (es. "2026-06-09")
    "url":      str,   # Link diretto all'annuncio (normalizzato, senza utm_*)
    "category": str,   # "tech" | "logistica" | "pulizie" | "retail"
    "source":   str,   # "jobs.ch" | "carriera.ch"
}
```

---

## Comuni Ammessi (Whitelist Rigida)

```python
COMUNI_AMMESSI = {
    "chiasso", "mendrisio", "stabio", "balerna",
    "coldrerio", "morbio inferiore", "novazzano", "riva san vitale"
}
```

- Confronto case-insensitive con `.lower().strip()`
- Qualsiasi annuncio con città non in questa lista viene scartato silenziosamente
- Annunci italiani (Como, Varese, Milano, ecc.) vengono scartati sia dal filtro città sia dal filtro dominio URL (nessun link `.it`)

---

## Parole Chiave per Categoria

```python
KEYWORDS = {
    "tech": [
        "Junior IT", "Help Desk", "Tecnico informatico",
        "Sviluppatore Junior", "Operaio elettronico", "Cablatore"
    ],
    "logistica": [
        "Magazziniere", "Addetto logistica", "Operaio generico",
        "Ausiliario di produzione", "Preparatore ordini"
    ],
    "pulizie": [
        "Ausiliario di pulizia", "Addetto pulizie", "Pulitore"
    ],
    "retail": [
        "Scaffalista", "Addetto vendita", "Cassiere"
    ],
}
```

---

## Strategia Anti-Blocco (Livelli Multipli)

| Livello | Tecnica | Dettaglio |
|---------|---------|-----------|
| 1 | Browser visibile (non headless) | `headless=False`, finestra minimizzata |
| 2 | Patch fingerprint | `playwright-stealth`: rimuove `navigator.webdriver`, falsifica Canvas/WebGL |
| 3 | User-Agent rotante | 5 UA Chrome reali, scelto a caso ad ogni run |
| 4 | Viewport realistico random | Tra `1366×768`, `1440×900`, `1920×1080` |
| 5 | Locale e timezone | `it-CH`, `Europe/Zurich` nel contesto browser |
| 6 | Sessione persistente | `profile/` salvato su disco, riutilizzato ad ogni run |
| 7 | Scrolling umano | Scroll progressivo della pagina prima dell'estrazione |
| 8 | Delay casuale | `random.uniform(3.0, 8.0)` secondi tra ogni ricerca |
| 9 | Retry con backoff | Max 3 tentativi, attesa 10s / 30s / 60s |
| 10 | Rilevamento blocco | Detecta pagine CAPTCHA/blocco → log warning → skip portale senza crash |

---

## Logica di Scraping per Portale

### jobs.ch
- URL base: `https://www.jobs.ch/it/lavoro/?term={keyword}&location=ticino`
- Attende rendering JS (selettore risultati)
- Estrae: titolo (`h2` o `h3` del card), azienda, città, data, URL
- Pagina successiva: gestisce paginazione fino a max 3 pagine per keyword

### carriera.ch
- URL base: `https://www.carriera.ch/offerte-di-lavoro?q={keyword}`
- Stessa logica di estrazione adattata ai selettori del portale
- Max 3 pagine per keyword

---

## Filtro e Deduplicazione (`filters.py`)

1. Unisce liste da entrambi i portali
2. Normalizza URL (rimuove `?utm_*`, `&utm_*` e altri parametri di tracking)
3. Deduplica per URL normalizzato — se duplicato, mantiene il primo trovato
4. Applica whitelist comuni
5. Scarta qualsiasi URL con dominio `.it`
6. Ritorna lista ordinata per data decrescente

---

## Dashboard HTML (`index.html`)

Generata da `html_generator.py` con Tailwind CSS via CDN.

### Componenti
- **Header:** titolo "Dashboard Lavoro Frontaliero", data/ora aggiornamento, badge contatore annunci totali
- **Barra filtri:** pulsanti JS "Tutti", "Tech/IT", "Logistica", "Pulizie", "Retail" — filtrano le card via `data-category` senza reload
- **Griglia card:** layout responsive (1 col mobile, 2 col tablet, 3 col desktop)
- **Card singola:**
  - Badge categoria (Blu=Tech, Verde=Logistica, Giallo=Pulizie, Arancione=Retail)
  - Titolo in grassetto
  - Nome azienda in grigio
  - `SVIZZERA – {Comune}` in evidenza
  - Data pubblicazione
  - Badge sorgente (jobs.ch / carriera.ch)
  - Bottone "Candidati Ora →" che apre `target="_blank"`
- **Stato vuoto:** messaggio visibile se 0 annunci trovati

---

## Hook LLM (Predisposto, Non Attivo)

Nel codice è presente la funzione commentata:

```python
# async def analyze_with_llm(job_text: str) -> dict:
#     """
#     Invia il testo dell'annuncio a Claude/OpenAI per estrarre:
#     - stipendio (se presente)
#     - se l'annuncio esclude i frontalieri (richiede residenza CH)
#     Richiede: pip install anthropic
#     API key: variabile d'ambiente ANTHROPIC_API_KEY
#     """
```

---

## Schedulazione Automatica (Windows Task Scheduler)

`setup_task_scheduler.bat` crea un task Windows che:
- Esegue `python scraper.py` ogni giorno alle **08:00**
- Usa il percorso assoluto di Python e dello script
- Il task si chiama `JobScraperFrontaliero`

Per rimuoverlo in futuro: `schtasks /delete /tn "JobScraperFrontaliero"`

---

## Dipendenze (`requirements.txt`)

```
playwright>=1.40.0
playwright-stealth>=1.0.0
```

---

## Istruzioni Avvio (`COME_AVVIARE.md`)

1. `pip install -r requirements.txt`
2. `playwright install chromium`
3. `python scraper.py` — primo test manuale
4. Doppio clic su `setup_task_scheduler.bat` — attiva avvio automatico ore 8:00
5. Apri `index.html` nel browser per vedere la dashboard

---

## Vincoli e Assunzioni

- Python 3.10+ installato e nel PATH di sistema
- Connessione internet attiva al momento dell'esecuzione
- Il computer deve essere acceso alle 08:00 per l'esecuzione automatica (se spento, il task non viene recuperato)
- La cartella `profile/` viene creata automaticamente al primo avvio
- I selettori CSS dei portali possono cambiare nel tempo — se lo scraper smette di trovare annunci, aggiornare i selettori nei file `scrapers/`

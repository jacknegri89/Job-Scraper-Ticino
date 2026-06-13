# Job Scraper Ticino

Raccoglie annunci di lavoro dai principali portali svizzeri, filtra quelli in Ticino e genera una dashboard HTML interattiva con analisi AI, stima dello stipendio netto e distanza da Barlassina.

## Cosa fa

- Scrapa 11 portali di lavoro svizzeri (jobs.ch, indeed.ch, LinkedIn, Adecco, Randstad, ecc.)
- Filtra automaticamente gli annunci per comuni del Ticino ammissibili
- Analizza ogni annuncio con OpenAI (adatto / non adatto al profilo, stima stipendio)
- Calcola il netto mensile stimato per i frontalieri italiani (Quellensteuer + IRPEF)
- Calcola la distanza in km da Barlassina (MB) per ogni sede di lavoro
- Genera `index.html`: dashboard dark con ricerca live, filtri per categoria e ordinamento

## Avvio rapido

```bash
# Installa dipendenze
pip install -r requirements.txt
playwright install chromium

# Scansione completa (scraping + AI + HTML)
python main.py

# Solo scansione siti, nessuna AI né HTML
python main.py --scan-only

# Probe veloce per testare raggiungibilità e cookie banner
python main.py --dry-run

# Solo un subset di siti
python main.py --only jobs.ch,indeed

# Browser nascosto (headless)
python main.py --headless

# Login manuale per LinkedIn/Indeed (salva la sessione per i run successivi)
python main.py --auth linkedin

# Riesegui solo l'analisi AI dalla cache (senza riscraping)
python main.py --reanalyze
```

## Struttura del progetto

```
main.py                  Entry point — CLI, loop siti, fasi descrizioni/AI/HTML
job_filter.py            Comuni ammessi, normalizzazione città/URL, dedup, categorie
distance_calculator.py   Distanza da Barlassina (formula haversine, offline)
salary_calculator.py     Stima netto frontaliero (lordo CHF → netto EUR/mese)
ai_analyzer.py           Analisi annunci con OpenAI gpt-4o-mini
dashboard_builder.py     Genera index.html (dashboard dark, ricerca, filtri)

scrapers/
  __init__.py            Browser anti-detection, stealth, retry decorator
  settings.py            Timeout, headless, tentativi (override da env SCRAPER_*)
  page_guard.py          Cookie banner per dominio, rilevamento login/captcha
  session.py             Login manuale (--auth) e sessioni salvate in profile/
  site_report.py         Stato per sito, scan_report.json, screenshot di debug
  jobs_ch.py             jobs.ch
  carriera_ch.py         carriera.ch
  gigroup_ch.py          gi group switzerland
  randstad_ch.py         randstad.ch
  orienta_ch.py          orienta.ch
  jobscout24_ch.py       jobscout24.ch
  indeed_ch.py           indeed.ch
  adecco_ch.py           adecco.com/it-ch
  manpower_ch.py         manpower.ch
  linkedin_ch.py         linkedin.com/jobs (Ticino)
  frontaliereticino_ch.py frontaliereticino.ch (indice JSON, no browser)
  monster_ch.py          monster.ch (disabilitato — portale non più attivo)

tests/                   48 test con pytest
```

## Output

Dopo un run completo trovi nella cartella del progetto:

| File | Contenuto |
|------|-----------|
| `index.html` | Dashboard interattiva da aprire nel browser |
| `jobs_cache.json` | Cache annunci con descrizioni e analisi AI |
| `scan_report.json` | Stato per ogni sito (ok / empty / blocked / ecc.) |
| `debug/` | Screenshot e HTML delle pagine problematiche |

## Configurazione

| Variabile d'ambiente | Default | Descrizione |
|----------------------|---------|-------------|
| `OPENAI_API_KEY` | — | Richiesta per l'analisi AI |
| `SCRAPER_HEADLESS` | `0` | `1` = browser nascosto |
| `SCRAPER_TIMEOUT_MS` | `30000` | Timeout navigazione in ms |
| `SCRAPER_ATTEMPTS` | `2` | Tentativi per scraper (max 3) |

## Test

```bash
python -m pytest tests/ -v
```

48 test coprono: filtri comuni, normalizzazione URL/città, generazione HTML, calcolo distanze, calcolo stipendio netto, retry decorator, rilevamento cookie/captcha/login gate.

## Note legali

Lo scraper usa solo endpoint pubblici e non automatizza mai login. Per LinkedIn e Indeed, il login si esegue manualmente una volta (`--auth linkedin`) e la sessione viene riutilizzata. Non vengono creati account finti né aggirate misure di sicurezza.

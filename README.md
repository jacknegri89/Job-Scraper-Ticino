# Job Scraper Ticino

[![CI](https://github.com/jacknegri89/Job-Scraper-Ticino/actions/workflows/ci.yml/badge.svg)](https://github.com/jacknegri89/Job-Scraper-Ticino/actions/workflows/ci.yml)

Applicazione locale che raccoglie annunci da portali svizzeri, li filtra per otto comuni del Mendrisiotto e genera una dashboard interattiva `index.html`. L'analisi AI è facoltativa. Configurazioni personali, sessioni e risultati generati non vanno versionati.

## Installazione

Serve Python 3.10 o successivo. Nella cartella del progetto:

```bash
python -m venv .venv
```

Attiva l'ambiente con `.venv\Scripts\activate` su Windows oppure `source .venv/bin/activate` su macOS/Linux, quindi esegui:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Chromium usa il proprio sandbox. Su Linux il sistema deve supportarlo: se il browser segnala un errore di sandbox, configura l'host prima di avviare lo scraper.

## Configurazione e avvio

Su Windows fai doppio clic su `Avvia.bat`: si apre nel browser predefinito un pannello locale con comuni, fonti, termini di ricerca per jobs.ch, distanza, analisi AI, timeout e tentativi. Su altri sistemi, o da terminale, usa `python main.py --panel`. Il pannello funziona solo su questo computer, tramite `127.0.0.1` e una porta temporanea.

Scegli le opzioni e premi **Salva impostazioni** oppure **Avvia ricerca**. La ricerca parte in background con il browser di raccolta nascosto; il pannello mostra lo stato e al termine il programma apre la dashboard. Il pulsante **Chiudi pannello** termina il pannello, senza interrompere una ricerca già avviata. Le scelte sono salvate nel file locale `user_settings.json`, escluso da Git. Per usare l'AI, imposta `OPENAI_API_KEY` nell'ambiente prima di aprire il pannello: la chiave non viene inserita né salvata nel pannello. Se attivi l'AI, il profilo viene inviato al modello insieme ai dati dell'annuncio.

Se possiedi già `user_config.py`, il pannello propone le coordinate e il profilo esistenti senza modificarlo. Finché non salvi la nuova configurazione, restano valide le impostazioni precedenti. Gli avvii automatici in background usano le impostazioni salvate; se non esistono usano le impostazioni precedenti.

Esegui dalla cartella del progetto:

```bash
python main.py
```

Il comando apre il pannello. Il programma raccoglie gli annunci, recupera le descrizioni consentite, riutilizza i dati in cache, esegue l'eventuale analisi AI e genera `index.html`. La dashboard include ricerca, filtri, distanze indicative, stime salariali e collegamenti agli annunci. È progettata per l'uso locale: la pubblicazione online richiede una verifica separata di dati personali, privacy e contenuti dei portali.

Lo script facoltativo `setup_task_scheduler.bat` configura su Windows un'attività giornaliera alle 08:00. Usa `--background --headless --project-dir` per eseguire la ricerca senza pannello e salvare i file nella cartella del progetto. Per aggiornare un'attività creata con una versione precedente, esegui nuovamente lo script.

## Comandi

| Comando | Funzione |
|---|---|
| `python main.py --scan-only` | Raccoglie gli annunci e scrive il report, senza descrizioni, AI, dashboard o modifica della cache. |
| `python main.py --dry-run` | Verifica rapidamente accesso, blocchi e selettori delle fonti. |
| `python main.py --only jobs.ch,indeed` | Limita la ricerca alle fonti indicate, mantenendo quando possibile i risultati delle altre fonti nella cache. |
| `python main.py --headless` | Avvia Chromium senza finestra visibile. |
| `python main.py --panel` o `--configure` | Apre il pannello di configurazione nel browser. |
| `python main.py --background --headless --project-dir` | Esegue la ricerca senza aprire il pannello. |
| `python main.py --project-dir` | Salva i file relativi nella cartella del progetto anche se avviato altrove. |
| `python main.py --timeout 45000` | Imposta il timeout di navigazione predefinito, in millisecondi. |
| `python main.py --auth linkedin` | Apre il login manuale LinkedIn e salva la sessione. |
| `python main.py --reanalyze` | Analizza dalla cache solo gli annunci senza risultato AI e rigenera la dashboard, senza nuova scansione. |

`--reanalyze` conserva i risultati AI esistenti anche se il profilo è cambiato. Lo scraper Indeed usa la modalità pubblica e non utilizza la sessione salvata con `--auth indeed`.

## Configurazione

| Impostazione | Dove | Funzione |
|---|---|---|
| Comuni, fonti, parole, coordinate, profilo, timeout e tentativi | `user_settings.json` | Scelte locali impostate nel pannello; prevalgono su `user_config.py`. |
| `HOME_LAT`, `HOME_LNG`, `HOME_CITY`, `CANDIDATE_PROFILE` | `user_config.py` | Configurazione precedente, ancora supportata se non esiste `user_settings.json`. |
| `OPENAI_API_KEY` | Variabile d'ambiente | Abilita l'analisi AI. Non inserirla nel codice. |
| `SCRAPER_HEADLESS` | Variabile d'ambiente | `1` avvia il browser senza finestra. |
| `SCRAPER_TIMEOUT_MS` | Variabile d'ambiente | Timeout predefinito di navigazione. |
| `SCRAPER_ATTEMPTS` | Variabile d'ambiente | Tentativi per scraper, limitati dal codice. |

I comuni selezionabili sono Chiasso, Mendrisio, Stabio, Balerna, Coldrerio, Morbio Inferiore, Novazzano e Riva San Vitale. I termini personalizzati si applicano a jobs.ch; gli altri portali hanno strategie proprie. Le distanze sono in linea d'aria. Le date sconosciute restano vuote; le date relative sono approssimative. La dashboard mostra solo le fonti selezionate; la cache può conservare i risultati delle altre fonti.

Le descrizioni vengono scaricate solo da host HTTPS dei portali previsti: richieste e reindirizzamenti verso altri host vengono bloccati. Il download usa un contesto separato, senza JavaScript né sessioni salvate. I link esterni restano nella dashboard, ma le descrizioni che richiedono siti esterni, login o JavaScript possono mancare.

## File principali

| File | Responsabilità |
|---|---|
| `main.py` | Comandi, coordinamento delle scansioni e cache. |
| `job_filter.py` | Località, termini, categorie, normalizzazione e duplicati. |
| `distance_calculator.py` | Distanze in linea d'aria. |
| `salary_calculator.py` | Stima indicativa del netto da un lordo mensile. |
| `ai_analyzer.py` | Analisi AI facoltativa. |
| `dashboard_builder.py` | Generazione della dashboard HTML. |
| `scrapers/` | Un modulo per fonte, browser, sessioni, rilevamento blocchi e report. |
| `tests/` | Test automatici di filtri, dashboard, cache, scraper e calcoli. |
| `requirements.txt` | Dipendenze di esecuzione e test. |
| `user_config.example.py` | Modello della configurazione personale locale. |
| `startup_config.py` | Procedura guidata, validazione e salvataggio delle scelte locali. |
| `setup_panel.py`, `setup_panel.html` | Server locale, pannello e avvio della ricerca in background. |
| `Avvia.bat` | Apre il pannello su Windows senza finestra di lavoro. |

I file generati `user_settings.json`, `scraper.log`, `index.html`, `jobs_cache.json`, `jobs_cache.partial.json`, `scan_report.json`, `debug/` e `profile/` sono esclusi da Git. Se una fonte fallisce, è bloccata o restituisce risultati incompleti o vuoti, i suoi annunci precedenti possono rimanere in cache e non essere aggiornati: controlla `scan_report.json`. Una scansione interrotta non sostituisce la cache principale. In caso di errore il pannello rimanda a `scraper.log`, che può contenere dati degli annunci e va trattato come file privato.

## Test

```bash
python -m pytest tests/ -v
```

I test coprono filtri, dashboard, distanze, stime, retry, cache, paginazione, validazione AI e filtro URL. Non dimostrano da soli il funzionamento attuale dei portali né misurano le prestazioni. Per una verifica rapida delle fonti usa `python main.py --dry-run`.

## Stime e privacy

Il lordo stimato dall'AI e il netto calcolato sono indicativi, non costituiscono un'offerta verificata o un calcolo fiscale personalizzato. Consulta l'annuncio originale e verifica le regole applicabili.

Non condividere o versionare `user_settings.json`, `user_config.py`, cache, sessioni, screenshot di debug e dashboard senza averli controllati: possono contenere profilo personale, coordinate, cookie, email di contatto o contenuti dei portali. Consulta le condizioni delle fonti e usa il login manuale dove previsto.

## Licenza

[Licenza MIT](./LICENSE) © 2026 Giacomo Negri.

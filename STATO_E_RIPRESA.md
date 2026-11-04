# Stato e procedura di ripresa

Ultimo aggiornamento: 2026-11-04

## Stato vincolante

- Repository: `jacknegri89/Job-Scraper-Ticino`.
- Repository GitHub: **privato**.
- Branch di lavoro: `codex/pannello-locale`.
- Commit di riferimento: `8dcc95cff9bd94cbbf86daa98ed2adbee56c19b1`.
- Branch `main`: volutamente non modificato e non è stato fatto alcun merge.
- Il codice applicativo del branch è **congelato fino all'esecuzione dei test**.
- Non modificare codice, README o configurazione prima di avere registrato l'esito dei test.
- I test automatici precedenti alla versione grafica erano passati, ma non certificano il pannello attuale.
- La versione grafica e il flusso in background non sono ancora stati eseguiti dopo l'ultima modifica.
- Non dichiarare il progetto funzionante finché la checklist seguente non è completata.

## Come riprendere da un altro computer

1. Clonare il repository privato e selezionare il branch di lavoro:
   ```powershell
   git clone https://github.com/jacknegri89/Job-Scraper-Ticino.git
   cd Job-Scraper-Ticino
   git switch codex/pannello-locale
   ```
2. Creare un ambiente virtuale senza usare installazioni globali:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```
3. Non copiare segreti nel repository. Se servono integrazioni opzionali, usare variabili d'ambiente locali e mantenere vuoto `.env.example`.
4. Leggere prima `AGENTS.md`, `README.md`, questo file e `DA_VERIFICARE.md`.

## Test obbligatori, nell'ordine

### 1. Test automatici

Eseguire dalla radice del repository:

```powershell
python -m pytest -q
```

Registrare: comando, data, versione Python, numero di test, errori e risultato `PASS` o `FAIL`.

Se `pytest` non è disponibile, installare le dipendenze dichiarate dal progetto nell'ambiente virtuale e ripetere. Non modificare i test per nascondere un errore.

### 2. Avvio del pannello

```powershell
python main.py
```

Verificare che:

- venga aperta la pagina su localhost nel browser predefinito;
- il pannello mostri le opzioni senza errori JavaScript;
- sia possibile selezionare città, fonti, termini di ricerca, coordinate, timeout e tentativi;
- il salvataggio generi `user_settings.json` locale, ignorato da Git;
- i dati inseriti vengano validati e non provochino traceback.

### 3. Avvio in background

Dal pannello premere il pulsante di avvio e verificare che:

- il processo dello scraper parta senza mostrare una console all'utilizzatore;
- il pannello rimanga utilizzabile;
- `scraper.log` venga creato localmente e resti ignorato da Git;
- lo stato mostri correttamente processo avviato, terminato o errore;
- non vengano inserite chiavi API o dati sensibili nei file versionati.

### 4. Verifica funzionale dello scraper

Usare una configurazione di prova limitata e controllare:

- caricamento delle impostazioni salvate;
- filtro per città;
- fonti selezionate;
- termini di ricerca personalizzati;
- timeout e retry;
- profilo AI opzionale disattivato per default;
- gestione di input vuoti, duplicati o non validi;
- assenza di crash se una fonte non risponde;
- contenuto e livello di dettaglio dei log.

### 5. Verifica di sicurezza e regressione

Controllare manualmente:

- pannello accessibile solo tramite localhost e token della sessione;
- richieste con Host/Origin non validi rifiutate;
- CSRF e rate limiting del pannello funzionanti;
- nessun segreto nel codice, nei log o nella cronologia Git;
- comportamento delle modalità CLI già esistenti;
- nessun `console.log`, `var_dump`, TODO di test o file temporaneo aggiunto per errore.

## Limitazione già nota da verificare

Il pannello controlla il processo avviato nella sessione corrente. Se il pannello viene chiuso e riaperto mentre uno scraper precedente è ancora in esecuzione, la nuova sessione potrebbe non riconoscere quel processo e potrebbe consentire un doppio avvio. Non correggere questa limitazione prima di averla riprodotta e documentata nei risultati dei test.

## Regola per le modifiche successive

- Se tutti i test passano: non cambiare il codice senza una motivazione documentata; preparare eventualmente una richiesta di merge verso `main`.
- Se un test fallisce: salvare prima l'errore completo, individuare la causa radice, modificare solo il necessario, ripetere tutti i test e aggiornare questo file.
- Ogni correzione deve essere fatta sul branch `codex/pannello-locale`, mai direttamente su `main`.
- Dopo ogni modifica significativa aggiornare `.claude/state.md` nel repository, mantenendolo breve e tecnico.
- Non fare merge o deploy finché la suite completa e le verifiche funzionali non risultano `PASS`.

## Chiusura del test su un computer temporaneo

Se il repository è stato clonato solo per la prova:

1. salvare nel branch remoto eventuali correzioni autorizzate;
2. verificare che non siano rimasti segreti o file locali da pubblicare;
3. uscire dall'ambiente virtuale;
4. eliminare soltanto la copia locale del progetto e il relativo ambiente virtuale;
5. lasciare il codice di riferimento su GitHub.

## Stato da aggiornare alla prossima sessione

Compilare sempre questa tabella nel commit successivo:

| Controllo | Esito | Note |
|---|---|---|
| `pytest -q` | DA ESEGUIRE | |
| Avvio pannello | DA ESEGUIRE | |
| Salvataggio configurazione | DA ESEGUIRE | |
| Avvio background | DA ESEGUIRE | |
| Log e chiusura | DA ESEGUIRE | |
| Test input non validi | DA ESEGUIRE | |
| Controllo sicurezza | DA ESEGUIRE | |
| Merge su `main` | BLOCCATO | attendere tutti i PASS |

Questo file è la memoria operativa del progetto: leggerlo prima di iniziare una nuova sessione e aggiornarlo dopo ogni verifica o correzione.

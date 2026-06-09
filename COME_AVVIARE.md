# Come avviare il Job Scraper Frontaliero

## Primo avvio (una volta sola)

1. Apri il Prompt dei Comandi nella cartella `Lavoro`:
   - Tasto destro sulla cartella -> "Apri nel terminale"

2. Installa le dipendenze:
   ```
   pip install -r requirements.txt
   playwright install chromium
   ```

3. Esegui lo scraper per testare:
   ```
   python scraper.py
   ```
   (Una finestra Chrome si apre automaticamente - non chiuderla)

4. Apri `index.html` nel browser per vedere la dashboard.

5. Configura l'avvio automatico ogni mattina alle 08:00:
   - Fai doppio clic su `setup_task_scheduler.bat`
   - Clicca "Si" se chiede i permessi di amministratore

## Uso quotidiano

Apri `index.html` ogni mattina - la dashboard si aggiorna in automatico alle 08:00.
Il computer deve essere acceso e connesso a internet all'orario configurato.

## Aggiornamento manuale

```
python scraper.py
```

## Problemi comuni

| Problema                   | Soluzione                                               |
|----------------------------|---------------------------------------------------------|
| pip non trovato            | Usa: python -m pip install -r requirements.txt          |
| "playwright non trovato"   | pip install playwright && playwright install chromium   |
| 0 annunci trovati          | Controlla la console per errori o selettori obsoleti    |
| Il task non parte          | Il PC deve essere acceso alle 08:00                     |
| Disattivare l'automatismo  | schtasks /delete /tn "JobScraperFrontaliero"            |

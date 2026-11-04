# Prove sul computer personale

Questa versione del pannello è stata preparata senza avviare il programma o installare nuovi prerequisiti sul computer aziendale dopo la richiesta dell'utente. Le prove funzionali seguenti restano da eseguire sul computer personale.

1. Scaricare il repository privato e seguire l'installazione nel README usando Python 3.10+ e l'ambiente virtuale locale.
2. Su Windows, avviare `Avvia.bat` e verificare che il browser predefinito mostri il pannello locale senza una finestra dei procedimenti dello scraper.
3. Scegliere comuni, fonti e termini; salvare, chiudere il pannello con il pulsante dedicato e riaprirlo. Verificare che le scelte siano rimaste.
4. Provare sia la ricerca con distanza disattivata sia l'inserimento di coordinate valide. Verificare che coordinate e scelte non valide siano rifiutate.
5. Avviare una ricerca, verificare che lo stato sia visibile e che non sia possibile avviarne un'altra contemporaneamente dallo stesso pannello. Controllare dashboard, filtri, fonti, località, cache e report `scan_report.json`.
6. Per l'AI, impostare `OPENAI_API_KEY` solo nell'ambiente locale prima di aprire il pannello. Attivarla solo se si desidera inviare il proprio profilo e i dati degli annunci al servizio. Verificare anche il messaggio quando la chiave manca.
7. Se usata, riconfigurare e provare l'attività pianificata Windows. Controllare che la scansione parta senza pannello, con file nella cartella del progetto.
8. Provare chiusura e riapertura del pannello. Una ricerca già avviata deve continuare dopo la chiusura del pannello.

Il pannello conserva lo stato della ricerca solo mentre resta aperto: dopo una riapertura non riconosce automaticamente una ricerca avviata dal pannello precedente. Evita di avviarne una seconda finché la prima non è terminata. La ricerca continua anche dopo la chiusura del pannello.

Non caricare su GitHub `user_settings.json`, `user_config.py`, chiavi, `scraper.log`, cache, dashboard generate, sessioni o screenshot: possono contenere dati personali. Una verifica reale dei portali può richiedere tempo e dipende dalla disponibilità delle fonti.

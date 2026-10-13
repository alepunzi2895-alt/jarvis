# Catalogo dinamico e analisi del lavoro

1. `core/projects.py` unisce note, `WS_*`, Git nelle cartelle immediate sotto
   le radici. Default: padre di JARVIS. Per altre radici/non-Git usa
   `.project-catalog.json` (ignorato), esempio in `project-catalog.example.json`.
   Non aggiungere liste fisse in bridge, status o UI. Non espandere automaticamente
   `JARVIS_ALLOWED_DIRS`: scoperta/lettura e scrittura sono permessi distinti.
2. Verifica una nuova cartella con `projects.catalog()` e `detect()`, poi
   `project_status.check_one_by_key()`. Le note sono storiche, non salute corrente.
3. Dashboard privata: history `_conversation`, focus `_focus` e modello
   `_analysis` per sessione. Il backend privato fornisce direttamente lo stato
   progetti con cache 30 s; non dipende dalla pubblicazione Turso del bot.
4. Outlook: agenda e conteggi, corpi mail solo dopo scelta dell'utente.
   Occupazione calendario = unione intervalli tagliati sul giorno; dati
   mancanti `None`, non zero. Non equipararla a produttivita'.
5. Focus espliciti in `.focus.sqlite3`, SQLite gestisce scritture concorrenti
   dei processi. Leggere non crea obiettivi. Nessun promemoria implicito.
6. Databricks QAS: OAuth gia' disponibile; `databricks_catalog.inspect()`
   usa solo GET. Controlla `count`, `partial`, `next_page_token` e periodo.
   Runs: 25/pagina, 100 e' rifiutato dall'API reale. Ogni pagina ha statistiche
   del proprio campione; non sommare medie/percentuali senza denominatori.
   Dashboard AI/BI: definizioni/query non sono risultati aggiornati. Per i
   risultati usa SQL di lettura aggregato. PRD mantiene conferma dedicata.
7. Prove reali: non stampare credenziali, corpi mail o sorgenti in massa.
   Isolare history e disabilitare `_run_post_processing` nei test API per non
   sporcare il second brain. Non misurare latenza vocale con una prova testuale.
8. Concludi tutte le modifiche/test prima di chiedere il singolo riavvio
   manuale di LiveBridge: vedi `autostart-windows-hidden.md`. Poi login HTTPS,
   `/live/ws` pronto e `project_status_data` con il nuovo catalogo.

9. Scansione Git in parallelo, snapshot unico 30 s per widget/tool/voce. Il
   riepilogo vocale generico usa al massimo due punti, senza giro LLM. Non
   ripristinare un elenco completo nel parlato per ogni progetto scoperto.
10. Rete segue il trasporto, mai il refresh di un widget. Per problemi al
    meteo distinguere dati assenti da pannello fuori viewport: controllare
    forecast, sette card, posizione sotto header e sopra dock su desktop.

# Memoria persistente e dati collegati JARVIS

## Quando
Verificare ricordi/correzioni, equity TradePilot o deploy Iveco dalla dashboard privata.

## Memoria
- `.memory.sqlite3` locale, esclusa da Git. Preferenze globali; fatti per progetto con fonte/data. Le preferenze recenti prevalgono su profilo e vecchie note.
- Richieste dirette `non mi nominare piu X e Y`, `ricorda che ...`, `puoi tornare a nominare ...` applicate senza LLM. Gli esempi ipotetici non sono comandi.
- Il modello puo apprendere selettivamente citazioni esatte dell'utente o dei file di progetto letti nel turno. Niente ipotesi salvate come fatti. Memoria esterna al modello, non addestramento dei pesi.
- Second brain -> Memorie apprese e preferenze mostra fonte/data e Dimentica (disattivazione). I vecchi nodi Turso restano separati: nessuna migrazione o cancellazione automatica.
- Esclusioni filtrate prima della voce e nel testo finale; non basta confidare nel prompt. Test sempre su DB temporanei, senza salvare esempi personali nella memoria reale.

## TradePilot
- `.tradepilot.json` privato: `origin` HTTPS della VPS sulla tailnet, eventuale `remote_key`; mai usare il Funnel pubblico redatto come API conto.
- GET fissi meta/autopilot/journal/research/factory; nessuna chiamata operativa. Dashboard e tool distinguono conto demo, shadow e ricerca.
- `.tradepilot.sqlite3` conserva un campione reale/minuto per conto; raccolta durante LiveBridge attivo. Grafico ultimi 1440 campioni, storico precedente non ricostruito, vuoti del PC spento non riempiti.
- Il registro ricerche VPS puo essere meno aggiornato del repository sul PC. Dichiarare fonte, data, campione e modalita. Equity comprende posizioni aperte e versamenti/prelievi; non chiamarla rendimento della strategia.

## Azure DevOps Iveco
- `.azure-devops.json` privato contiene project_url e tenant. Azure CLI Microsoft ufficiale; cache isolata `.azure-auth/` esclusa da Git, token mai stampati.
- Rinnovo: `powershell -File setup_devops.ps1`, selezione account aziendale e MFA personale.
- Su questo PC il device-code dichiarava accesso completato nel browser ma restava bloccato nel client. Funziona login Windows con `--skip-subscription-discovery --scope 499b84ac-1321-427f-aa17-267ca6975798/.default`.
- GET soli: ultima build per pipeline (30), timeline prime 10, release classiche (20), ambienti (30) e 5 record per ambiente. Cache 30s, errori/copertura incompleta espliciti.
- Data Room usa fasi `Deploy to PROD/QAS` nella timeline, senza record in Azure Environments/classic releases. Controllare sempre le fasi: build succeeded da sola non prova deploy. skipped non e un errore. Avvisi job separati; nessuna lettura dei log grezzi.
- Il codice non avvia/approva/annulla deploy. L'account Microsoft mantiene i propri permessi aziendali: non dichiarare che il token in se sia limitato alla sola lettura.

## Attivazione
- Finire codice, test, commit/push prima dell'unico riavvio LiveBridge. Seguire `autostart-windows-hidden.md` per la chiusura manuale del PID corrente.
- Dopo avvio: HTTPS login, WS/STT ready, memories_list, tradepilot_data e devops_data. Non stampare password/token o numeri di conto.

Riferimento API timeline: https://learn.microsoft.com/en-us/rest/api/azure/devops/build/timeline/get?view=azure-devops-rest-7.1

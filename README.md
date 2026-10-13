# JARVIS — fase 1
stopp
Telegram -> Claude Code sul tuo PC. Nessun tunnel, nessuna porta aperta.

## Setup (10 min)

**1. Crea il bot**
Telegram -> `@BotFather` -> `/newbot` -> copia il token.
Telegram -> `@userinfobot` -> copia il tuo user id.

**2. Configura**
```
copy .env.example .env      (Windows)
cp .env.example .env        (Mac/Linux)
```
Compila `TELEGRAM_TOKEN`, `TELEGRAM_OWNER_ID`, i path `WS_*`.

Windows: `CLAUDE_BIN` di solito è
`C:\Users\<TU>\AppData\Roaming\npm\claude.cmd`
(verifica con `where claude`)

**3. Avvia**
```
start.bat        (Windows)
./start.sh       (Mac/Linux)
```

## Uso

| Comando | Cosa fa |
|---|---|
| `/ws aura` | passa al workspace AURA |
| `/new` | azzera la sessione |
| `/status` | workspace + sessione attiva |
| `/log` | log di oggi |
| testo libero | task da eseguire |

Esempi:
- `/ws aura` poi `Genera 5 caption IG per Cala Tarida, EN/ES/IT`
- `/ws trading` poi `Leggi ultimo export MT5, dammi report della settimana`
- `/ws vino` poi `Rigenera il catalogo con i prezzi aggiornati`

## Sempre acceso
- Windows: Utilità di pianificazione -> attività all'accesso -> `start.bat`
- Mac: `launchd` plist, oppure `pm2 start start.sh`

## Dashboard su iPhone

- Apri la dashboard in Safari; puoi aggiungerla alla schermata Home.
- Un pannello alla volta, controlli touch da 44 px e layout che segue la
  tastiera e le aree sicure dello schermo. La barra comandi scorre lateralmente.
- Tocca il microfono, autorizzalo e pronuncia «Jarvis» seguito dal comando.
  Su mobile l'ascolto si ferma cambiando app o interrompendo l'audio: per
  riprenderlo torna alla pagina e tocca il microfono. Non è un wake word di sistema.
- Per audio diretto e risposta sul telefono usa l'indirizzo privato Tailscale
  descritto sotto. La dashboard Vercel mantiene il percorso precedente
  attraverso Turso e la riproduzione sul PC.

Per ridurre la latenza completa servono una GPU con runtime compatibile,
trascrittore già caricato, connessione persistente al PC e risposta generata
e riprodotta per frasi. Le operazioni lunghe devono mostrare un avanzamento
senza essere dichiarate concluse prima dell'esito. Misurare il tempo dalla
fine del parlato al primo audio reale; un'animazione non vale come risposta.

Test del browser con API e microfono simulati, senza accesso al DB reale:

```powershell
.venv/Scripts/python.exe -m playwright install chromium webkit
.venv/Scripts/python.exe -m pytest -q tests/test_dashboard_mobile.py
```

L'emulazione WebKit non sostituisce la prova di permessi, microfono e tastiera
su un iPhone fisico.

### Collegamento diretto iPhone-PC

1. Installa Tailscale sul PC e sull'iPhone, accedi allo stesso account e
   lascia accesa la VPN Tailscale sul telefono.
2. Sul PC, dopo avere installato `requirements.txt` nella `.venv`, esegui:

   ```powershell
   .\setup_live.ps1 -Start
   ```

3. Apri in Safari l'indirizzo HTTPS stampato dallo script (porta 8443).
   Accedi con la password nel file locale `.live-password`, poi tocca il mic.
   `JARVIS_LIVE_PASSWORD` nel `.env` permette di scegliere una password diversa.
4. **Attiva audio** sblocca/riprende l'uscita di Safari; **Stop** ferma subito
   l'audio e annulla il turno. Se un'azione sul PC e' gia' partita, puo' dover
   terminare prima di accettare il comando successivo.

`LiveBridge` parte nascosto all'accesso Windows. Il servizio ascolta solo su
`127.0.0.1:8765`; Tailscale Serve fornisce HTTPS nella rete privata. Nessun
Funnel pubblico. PC acceso, sessione Windows attiva e rete raggiungibile sono
necessari. Log: `logs/live.log`. Rimuovi l'avvio automatico con
`uninstall_live.ps1`; lo script non termina processi attivi.

Gli audio acquisiti vanno direttamente al PC via WebSocket, vengono trascritti
da Whisper gia' caricato e restano solo in RAM. Nessun fallback alla coda cloud
in caso di disconnessione. Claude riceve testo e le eventuali immagini inviate
esplicitamente; la sintesi edge-tts riceve il testo della risposta. Il second
brain continua a salvare le interazioni testuali con il comportamento esistente.
La cronologia della sessione privata rimane in RAM (ultime 20 risposte); gli
audio storici del vecchio percorso conservano il limite di 5 in Turso.
Il task Windows `AudioCleanup` applica la pulizia ogni 5 minuti anche quando
il vecchio bridge non e' stato riavviato. Gli audio ancora in elaborazione
sono esclusi dalla pulizia per non perdere comandi pendenti.

Le risposte API arrivano per frasi mentre vengono generate e sintetizzate. I
turni diretti usano `JARVIS_VOICE_MODEL` (default Haiku) con gli stessi tool;
il modello testo di Telegram/vecchia dashboard resta invariato. La prima
frase risponde subito in poche parole, poi seguono i dettagli necessari. I
comandi rapidi mantengono il percorso senza LLM; trading/CLI conserva i tool
esistenti e puo' richiedere piu' tempo. Le sessioni API/CLI private non scrivono
lo `state.json` condiviso dal bot. Il contesto meteo/memoria viene preparato in
background ogni minuto, senza una lettura di rete prima di ogni domanda.

La console mostra STT, primo testo e primo audio **inviato dal PC**, misurati
dalla ricezione del comando; non includono la pausa di 800 ms, il trasporto
in ingresso e il tempo fino alla riproduzione fisica. Non sono una misura
completa fine-parlato/primo-suono.

Su questa T1200, il driver 517.13 causa `CUDA driver version is insufficient`:
il fallback CPU e' operativo, ma il quasi immediato vocale resta limitato dalla
trascrizione. Servono driver e librerie compatibili prima di usare la GPU
([requisiti faster-whisper](https://github.com/SYSTRAN/faster-whisper#gpu)).
Il modello non viene ridotto automaticamente a scapito della precisione.

Test isolati del servizio e del browser:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_live_server.py tests/test_claude_bridge.py tests/test_dashboard_mobile.py
```

## Conversazione unica, lavoro e progetti

Nella dashboard privata la conversazione mantiene gli ultimi 8 scambi anche
quando cambia progetto. I comandi rapidi entrano nella stessa cronologia.
Analisi, confronti, pianificazione e coaching usano `JARVIS_TEXT_MODEL`;
le altre richieste mantengono `JARVIS_VOICE_MODEL`. TradingView esplicito
conserva il CLI/MCP. I canali Telegram/voce desktop mantengono il proprio
instradamento: la cronologia unica riguarda la dashboard privata.

Il catalogo unisce `memory/projects/*.md`, variabili `WS_*` e repository
nelle cartelle immediatamente sotto la cartella padre di JARVIS. Si aggiorna
senza riavviare; la panoramica privata conserva una cache di 30 secondi.
Nessuna scansione ricorsiva del disco. Per altre radici/cartelle senza Git,
copia `project-catalog.example.json` in `.project-catalog.json` e adatta i
percorsi. Questo file personale resta fuori da Git. Un progetto remoto
registrato solo per nome non rende accessibili i suoi contenuti.

Gli strumenti permettono di leggere note e file testuali locali (256 KB
massimi, estratto fino a 16.000 caratteri), elencare cartelle e verificare
Git. PDF, Excel e allegati Outlook non vengono automaticamente indicizzati.
La scoperta **non aggiunge permessi di scrittura**: per modifiche/CLI resta
necessaria la whitelist esistente `JARVIS_ALLOWED_DIRS`.

Esempi nella stessa conversazione:

- «Organizza oggi usando agenda e obiettivi: dammi tre priorita'.»
- «Confronta lo stato di EYRA, VMScout e Aura.»
- «Analizza i job Databricks QAS degli ultimi sette giorni.»
- «Leggi la definizione di questa dashboard e spiegami le query.»
- «Aiutami a scegliere cosa finire prima questa settimana.»
- «Registra l'obiettivo: chiudere il report entro il 16 ottobre.»

`get_work_overview` legge Outlook locale, stato Git attuale e obiettivi
espliciti. Il tempo occupato usa l'unione degli intervalli, include eventi
iniziati il giorno precedente e non equivale a ore lavorate. I dati mancanti
sono segnalati come non disponibili, non come zero. `focus_items` conserva
obiettivi/scadenze e completamenti confermati in `.focus.sqlite3` locale,
escluso da Git. Non crea notifiche, impegni o obiettivi autonomamente.

`inspect_databricks` usa l'OAuth QAS gia' configurato: job, run, dashboard
AI/BI (Lakeview), definizioni/query delle dashboard, cartelle e sorgenti
notebook richiesti. Nessun avvio o modifica di job. Risultati limitati ai
permessi del service principal; gli elenchi restituiscono conteggio della
pagina, `next_page_token` e `partial`. Le statistiche dei run riguardano la
pagina mostrata (25 run), dichiarano il periodo e il denominatore degli
esiti conosciuti. Non sono statistiche dell'intero workspace se `partial`
e' vero. Il modello puo' richiedere altre pagine. `query_databricks` riusa
SQL QAS sola lettura; per totali reali usa aggregazioni SQL, non il conteggio
delle righe del campione (massimo 100, visualizzate fino a 50).
PRD mantiene il percorso di conferma esistente. Genie richiede uno Space ID
separato: non serve per questo inventario e non viene configurato da solo.

Riferimenti API: [job e run](https://docs.databricks.com/api/jobs/v2/list-runs),
[dashboard AI/BI](https://docs.databricks.com/api/lakeview/v1/list-dashboards),
[lettura notebook](https://docs.databricks.com/api/workspace-objects/v1/export).

## Come impara
Ogni task scrive in `memory/log/`. Le procedure riuscite finiscono in
`memory/playbooks/`. La sessione dopo li rilegge (regola in `CLAUDE.md`).
Memoria = git. `git commit` la memoria ogni settimana.

## Fase 2
- Cron notturno: report trading + bozze contenuti al risveglio.
- Bottoni Approva/Rifiuta su Telegram per le azioni sensibili.
- UI Vercel se serve più della chat.

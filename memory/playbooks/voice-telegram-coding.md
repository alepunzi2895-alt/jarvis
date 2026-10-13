# Voce PC, Telegram e lavori Codex/Claude Code

## Ascolto
- Dashboard privata: microfono attivo con un clic, poi "Jarvis" + comando.
  VAD RMS 0.012; la vecchia soglia 0.06 scartava anche voce bassa.
  Silenzio e clic isolati restano filtrati. Audio senza parola di attivazione:
  messaggio esplicativo, nessuna risposta inventata. La pagina cloud mantiene
  la soglia precedente e non e il percorso consigliato.
- PC: task `\JARVIS\VoiceDaemon`, "hey jarvis" oppure Ctrl+Alt+J. Controllare
  anche processo e `logs/voice.log`, non soltanto lo stato del task.
  Readiness stampata dopo caricamento modelli e registrazione hotkey.
- Se entrambi non rispondono, distinguere soglia/permessi microfono, daemon
  fermo, trascrizione e API. Il 2026-10-13 Bot e VoiceDaemon erano fermi;
  la causa della loro precedente uscita non e stata isolata.
- Voce nativa e dashboard condividono Engine, strumenti e memoria. Il daemon
  mantiene un event loop per piu turni; niente client async riusato su loop
  gia chiusi. Nessuna prova simulata sostituisce il parlato dell'utente.
- Streaming Anthropic: i blocchi ParsedTextBlock hanno `parsed_output`,
  metadato SDK non accettato dall'API. Escludere `__api_exclude__` prima di
  reinviare la risposta dopo un tool; altrimenti HTTP 400 al secondo passaggio.

- Testo e pulsanti non aspettano la trascrizione di un audio sullo stesso
  socket: l'audio in corso viene scartato (ignored) e il comando parte subito.
  Prima del 2026-10-13 rispondevano "Sto trascrivendo il comando precedente."
  e sembravano bloccati, soprattutto a batteria (STT ~16 s) con VAD 0.012.

## Telegram
- Bot configurato: https://t.me/zerodayzz_bot. Task `\JARVIS\Bot`.
- Testo e note vocali solo dall'owner configurato. Le note non richiedono
  la parola "Jarvis". Massimo 3 minuti e 20 MB; trascrizione Whisper sul PC.
- Il file OGG temporaneo viene rimosso anche se la trascrizione fallisce.
  L'audio passa necessariamente da Telegram; nessun servizio STT cloud.
- Gli errori HTTP non devono contenere il token. `telegram.safe_error`
  maschera credenziali anche negli errori di polling/download. Vecchio log
  bonificato il 2026-10-13; credenziale esposta da rigenerare con BotFather.
- getMe/getWebhookInfo verificano bot e assenza webhook senza inviare messaggi;
  non eseguire getUpdates in parallelo al bot gia attivo.

## Codex e VS Code
- `open_coding_project`: apre il progetto del catalogo dinamico in Codex o
  VS Code (provider claude). `start_coding_task`: prompt esplicito in background.
- `coding_tasks`: registro locale `.coding.sqlite3`, ignorato da Git e protetto
  dal lettore file dei progetti. Stato/risposta visibili in Panoramica e
  richiedibili nella conversazione; richieste Telegram ricevono anche l'esito.
- Sono sessioni CLI vere e riprendibili con `previous_job`, non digitazione
  nella chat GUI gia aperta. Il registro contiene i lavori avviati da JARVIS,
  non tutte le conversazioni presenti nelle applicazioni.
- Sola lettura di default. Modifiche solo se richieste e cartella autorizzata;
  un solo lavoro alla volta per progetto. Nessun push/deploy automatico.
- Codex: `--no-daemon -a never -s read-only|workspace-write exec`, JSON eventi,
  configurazione utente ignorata ma login conservato. Su questo PC si usa
  esplicitamente la sandbox Windows `unelevated` gia configurata. Nessun bypass.
- Claude Code: `-p --output-format json`, strumenti Read/Glob/Grep (+ Edit/Write
  se autorizzati), nessun Bash, nessun MCP aggiuntivo, permessi non presidiati
  negati. `permission_denials` produce stato blocked con risposta effettiva.
- `done` significa risposta finale disponibile: leggere l'esito prima di
  dichiarare riuscita un'azione. Errori e interruzioni non sono successi.
- Risolvere gli eseguibili anche fuori dal PATH: i task Windows possono
  ereditare quello precedente all'installazione delle applicazioni.

## Prove e attivazione
- Pytest completo; test UI Chromium/WebKit con audio sintetico RMS .025 e
  rumore .005. Nessun audio reale inviato dalla suite.
- Smoke test CLI: fixture dentro `.tmp/coding-proof`, fuori dai dati personali;
  lettura, modifica di un singolo file e ripresa della stessa sessione.
  Una TemporaryDirectory Windows con ACL ristrette puo impedire la lettura
  alla sandbox Codex anche se i normali progetti sono accessibili.
- Completare codice/test/commit/push PRIMA di riavviare. Avviare direttamente
  solo i task gia fermi. Per il LiveBridge ancora vivo seguire il playbook
  `autostart-windows-hidden.md`: una sola chiusura manuale, poi porta libera,
  Start-ScheduledTask e verifica HTTPS/login/WS/STT/API coding_tasks.

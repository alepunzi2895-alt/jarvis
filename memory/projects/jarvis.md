# JARVIS — stato progetto

## Cos'è
Assistente personale di Alessandro: bot Telegram + dashboard web, entrambi bridge
verso un processo locale `claude -p`. Vedi `core/claude_bridge.py`, `core/web_bridge.py`.
Ha anche un second brain: memoria a lungo termine che Claude stesso consulta e
alimenta task dopo task (`core/brain.py`), visualizzata come grafo animato nella
dashboard.

## Stato attuale (2026-10-13)
`main` (merge `10b25cd`) contiene tutto `codex/unified-assistant`: voce privata
iPhone-PC via Tailscale (LiveBridge, porta 8765, HTTPS 8443), conversazione unica
tra progetti, memoria persistente, TradePilot/Azure DevOps in sola lettura,
Telegram testo/note, lavori Codex/Claude Code tracciati. Deploy Vercel
automatico riuscito, pagina cloud senza errori JS. Suite 461 test.
- Dopo reboot Tailscale resta `NoState` finche' non parte `tailscale-ipn.exe`
  (GUI): senza, il nome *.ts.net non risolve e la dashboard iPhone e' muta.
- A batteria whisper small CPU impiega ~16 s per segmento (contro ~2 s in carica).

## Stato precedente (2026-07-14)
`main` è aggiornato e **deploya correttamente in produzione**, verificato in
browser (dati TradeFlow live, non mock). Contiene fix del bridge web, restyle HUD
e second brain insieme.
- Fix bridge: il poller web parla con Turso via HTTP pipeline diretta
  (`core/web_bridge.py`), non passa dal gateway Vercel (POST resettate su rete
  aziendale).
- HUD: quadrante circolare animato, readout, cornici ad angolo su tutti i
  pannelli (`web/public/*`).
- Second brain: `core/turso.py` (client Turso condiviso), `core/brain.py`
  (`fetch_context()`/`extract_and_store()`, tabelle `brain_nodes`/`brain_edges`,
  bootstrap automatico), `core/claude_bridge.py` inietta contesto prima di ogni
  `claude -p` e processa il blocco ` ```brain ``` ` dopo. Dashboard: pulsante 🧠
  in header, grafo a forze su `<canvas>` (nodi colorati per workspace, enfasi su
  pill attiva o nodo cliccato). Parte vuoto finché un task vero non ci scrive
  qualcosa dentro.
- I branch `fix/web-bridge-blocking`, `feature/hud-ui`, `feature/second-brain`
  sono stati cancellati (locali e remoti) — erano interamente contenuti in `main`.

## Deploy — risolto: Root Directory, non Deployment Protection
Il 404 ricorrente su `jarvis-dashboard-green.vercel.app` **non era** la
Deployment Protection (ipotesi iniziale sbagliata, vedi log 12:35). Causa vera:
`Project Settings → Build and Deployment → Root Directory` era `./` (radice del
repo) invece di `web/` — i deploy automatici innescati dai push GitHub durante
questa sessione costruivano dal punto sbagliato e non trovavano niente da
servire (build da 36ms, nessun file preparato), da cui 404 su *tutti* i domini
del progetto, non solo l'alias "green". Il deploy che funzionava a inizio
sessione era un deploy manuale fatto da Alessandro via CLI da dentro `web/`
(che ignora quel campo perché il progetto è linkato lì), sostituito poi dai
deploy automatici rotti innescati dai miei push.

**Fix applicato**: Root Directory → `web` (fatto da Alessandro, non è una
security setting). Il pulsante "Redeploy" nella UI Vercel non è affidabile via
automazione browser — risolto forzando un rebuild pulito con un commit vuoto +
push su main. Verificato: tutti i path (`/`, `/style.css`, `/app.js`,
`/api/jarvis`) e l'alias "green" rispondono 200.

**Da controllare se capita ancora**: `tradeflow-ai` e `whitesoulibiza` usano lo
stesso pattern di alias "vanity" *.vercel.app — vale la pena controllare la loro
Root Directory se in futuro danno lo stesso 404.

## Prossimi passi noti
- Nessuno bloccante sul deploy.
- Il grafo second brain si popola solo con un task vero (`claude -p` reale che
  emette un blocco ` ```brain ``` `), non con i dati finti usati per verificare
  il rendering in sessione.
- Fase social (AURA + WhatsApp) resta bloccata da credenziali Meta che solo
  Alessandro può ottenere.
- Ascolto continuo del browser (`web/public/app.js`) ora richiede la parola
  "Jarvis" nella frase prima di sottoporre un task — senza, aveva captato ore
  di rumore ambientale e generato ~230 task spuri (~$1.33 di chiamate Claude
  reali prima che il filtro esistesse). Vale come precedente per qualsiasi
  futuro ascolto "sempre attivo".
- Il bridge locale (`bot.py`) va avviato manualmente ad ogni riavvio del PC —
  non c'è ancora un'attività pianificata di Windows per l'avvio automatico
  (proposta ma non fatta, è una modifica persistente al sistema da confermare
  con lui prima di farla).

## JARVIS v2 — in corso (spec di Alessandro, 10 sotto-sistemi)

Piano approvato in Plan Mode a blocchi. Piano architetturale del blocco più
recente in `C:\Users\f45038c\.claude\plans\rosy-percolating-rivest.md`
(riscritto ad ogni nuovo blocco — non è uno storico, solo il piano corrente).

**Tutto mergiato in main** (blocchi a, c1, c2, d) — su richiesta esplicita di
Alessandro ("mergia tutto su main sempre", vedi [[feedback-merge-to-main]]):
- **(a)** `core/obsidian.py` (`ObsidianVault`+`VaultWatcher`),
  `core/system_executor.py` (`SystemExecutor` — sicurezza a **whitelist**,
  scelta esplicita), comandi Telegram `/note /search /run /confirm /deny`.
- **(c1)** Dashboard riscritta come HUD a finestre fluttuanti attorno a una
  palla centrale animata (respiro + deriva + hue-rotate continuo, ritoccata
  più grande/futuristica su richiesta). Camera (round-trip immagine→Claude),
  comandi vocali browser che aprono finestre, second brain specchiato come
  note reali in Obsidian, `open_app` con risoluzione dinamica via registro
  Windows.
- **(c2)** Daemon vocale nativo: `core/voice/` (wake_word.py openWakeWord
  modello "hey_jarvis" preaddestrato, stt.py faster-whisper "small" CPU,
  tts.py edge-tts gratis, camera.py OpenCV per cattura webcam nativa),
  persona "Signore"/British/gentile solo su `channel="voice"` (modello
  haiku, più leggero, dato che le risposte vocali sono già vincolate a
  due frasi), `/voce on|off`.
  **Limite noto, non risolvibile lato config**: il modello "hey_jarvis"
  non riconosce la voce/accento di Alessandro (punteggio sempre
  <0.02 contro soglia 0.5, testato su tutti i canali del mic array) — al
  suo posto c'è la hotkey globale **Ctrl+Alt+J** (libreria `keyboard`),
  che avvia lo stesso identico ciclo.
  **Bug reali trovati e risolti** (in ordine di scoperta): (1) Windows
  cambia il microfono di default quando colleghi una cuffia — fix
  `JARVIS_MIC_DEVICE`/`resolve_input_device()`; (2) TTS crashava l'intero
  daemon cancellando l'mp3 temporaneo mentre PyAV lo teneva ancora aperto
  — fix `container.close()` esplicito; (3) il thread che ascolta
  un'interruzione durante il parlato restava agganciato al modello wake
  word (non thread-safe) fino a 15s dopo la risposta, bloccando il ciclo
  successivo — fix `cancel_event` + `join()` prima di procedere; (4) su
  Windows, `print()` su testo trascritto con caratteri non-ASCII
  (em-dash, accenti) crashava l'intero ciclo in silenzio — fix
  `sys.stdout.reconfigure(encoding="utf-8")`, il più serio dei quattro
  perché falliva senza NESSUNA risposta né traccia visibile. Aggiunto
  anche `JARVIS_SPEAKER_DEVICE`/`resolve_output_device()` come rete di
  sicurezza per l'uscita audio (verificato con loopback Stereo Mix che il
  software produce comunque audio vero).
- **(d)** `core/browser.py`: `BrowserAgent` (Playwright, profilo Chromium
  persistente `.browser_profile/`) — stesso pattern del second brain, Claude
  emette un blocco ` ```browser``` ` quando serve navigare un sito vero.
  Sicurezza a vocabolario limitato (solo open/search/screenshot, niente
  click/fill generico). Verificato con YouTube vera: cerca e apre il primo
  risultato corretto.

**Blocco (b) — EnvironmentRouter + MCPRouter**: unico ancora in pausa. Manca
il path per l'ambiente IVECO; da chiedere se vuole aggiungere altri MCP
server oltre TradingView (unico realmente configurato oggi).

## JARVIS v3 — controllo OS reale, fix webcam, riconoscimento volto (2026-07-15, branch `feature/jarvis-v3-os-control`)

Su segnalazione di Alessandro (voce lenta, "chiudi Chrome" non esisteva,
webcam rotta, vuole riconoscimento volto, microfono sembra sordo
all'avvio, grafo second brain tagliato). Dettaglio completo nel log delle
18:00. Riassunto architetturale:

- **Controllo OS reale** (prima non esisteva per voce/chat, solo `/apri`
  esplicito): `core/system_executor.py` esteso con `close_app` (psutil),
  `volume`, `lock_workstation`, `show_desktop`, `screenshot`,
  `power_action` (shutdown/restart/logoff, sempre dietro conferma).
  `core/intents.py` (nuovo): intercetta frasi brevi (≤10 parole) ed
  esegue subito, senza `claude -p` — zero costo/latenza per i comandi
  semplici. `core/system_actions.py` (nuovo, stesso pattern di
  `core/browser.py`): blocco ` ```system``` ` che Claude puo' emettere
  per le richieste composte che intents.py lascia passare. Spegnimento/
  riavvio/logout dal canale **vocale** sono rifiutati a priori (redirect
  a Telegram/dashboard, dove serve comunque `/confirm`). Nuovo
  `core/executor_singleton.py` (istanza condivisa fra bot.py/
  web_bridge.py/daemon.py, evita import circolare con claude_bridge).
- **Webcam**: bug reale trovato in DUE punti indipendenti — ne'
  `core/voice/camera.py` ne' `web/public/app.js` riconoscevano la parola
  "webcam" (solo camera/telecamera/fotocamera), quindi "apri la webcam"
  cadeva come task generico e Claude improvvisava aprendo un browser.
  Fissato in entrambi i punti.
- **Riconoscimento volto**: `core/voice/face_id.py`, OpenCV LBPH
  (richiede `opencv-contrib-python`, non `opencv-python` — sostituito).
  Solo personalizzazione, non sicurezza. `/enroll_face` su Telegram per
  arruolare Alessandro (~20 frame webcam). Dati in `.face_data/`
  (gitignored, biometrico). **Nota per il futuro**: la wheel pip di
  opencv-contrib-python 5.0.0.93 non include le Haar cascade XML in
  `cv2/data/` — cascade committata in `core/voice/data/` invece di
  dipendere dal pacchetto.
- **Velocita' voce**: whisper pre-caricato all'avvio del daemon
  (`stt.warm_up()`) invece che alla prima trascrizione reale — probabile
  causa del "non mi sente appena parte". Il pavimento di ~11-12s per
  risposta vera (CLI `claude -p` per messaggio) resta invariato: per
  scendere sotto serve l'API diretta invece del CLI, non fatto oggi.
- **Persona vocale**: non piu' tetto rigido di due frasi — resta breve
  per le conferme d'azione, risposte complete per domande vere.
- **Grafo second brain**: `web/public/app.js` ora fa zoom-to-fit
  (bounding box ricalcolato ogni frame) — prima disegnava a scala 1:1 e
  con molti nodi si vedeva solo il cluster centrale.

**Non ancora verificato dal vivo** (richiede lui): comandi OS reali a
voce/testo, `/enroll_face` + riconoscimento successivo, grafo completo
nel browser vero.

**Voce su API Anthropic diretta** (stesso giorno, branch
`feature/jarvis-voice-direct-api`, gia' mergiato): `core/claude_api.py`
sostituisce `claude -p` SOLO per il canale vocale — Telegram/dashboard
restano su `core/claude_bridge.py`. Second brain in sola lettura per la
voce (niente scrittura di nodi). Cronologia conversazione voce in memoria
di processo, non persistita (si azzera al riavvio del daemon).
**Bloccante**: manca `ANTHROPIC_API_KEY` nel `.env` — l'autenticazione del
CLI `claude` (login/abbonamento) non vale per l'SDK Python diretto, sono
due sistemi di credenziali separati. Il daemon risponde a voce "manca la
chiave API" finche' non viene aggiunta.

**Vault Obsidian reale**: `C:\Users\f45038c\Downloads\jarvis\jarvis\` (creato
da Obsidian stesso dentro il repo del codice — riconosciuto dal `.obsidian/`
interno). Escluso da git (`/jarvis/` in `.gitignore`).

**Ambienti locali sotto `C:\Users\f45038c\Downloads\`**: `conciergebookings` =
progetto **AURA** (`WS_AURA` in `.env`); `ConciergeFlow` = progetto a sé, non
ancora un workspace nominato; `conciergebooking` (singolare) = da ignorare.
Whitelist `SystemExecutor` = repo JARVIS + `ConciergeFlow` +
`conciergebookings` + `property_scout`/`VMScout`/`tradeflow-ai`/`whitesoulibiza`.

**Decisioni architetturali chiave**:
- Moduli Python diretti (Obsidian/SystemExecutor/Browser/futuro MCPRouter),
  non instradati per forza da `claude -p` — dove serve velocità (voce), o
  dove Claude emette un blocco strutturato (` ```brain``` `/` ```browser``` `)
  che un modulo diretto esegue — stesso pattern per entrambi.
- MCP server realmente configurati oggi: solo **TradingView**.
- Il browser NON potrà mai lanciare app native (Chrome standalone, VS Code)
  dalla dashboard web — solo dal bridge locale/daemon vocale. L'automazione
  Playwright (blocco d) è un browser SEPARATO controllato da Python, non
  soggetta a questo limite.
- Reti di questa macchina: blip DNS/timeout transitori ricorrenti durante
  questa sessione (Turso, cdn.playwright.dev) — sempre risolti da soli in
  pochi minuti, coerente con [[network-quirks-this-pc]].

## JARVIS v3.1 — meteo, log di ogni interazione, hardening second brain (2026-07-16, branch `feature/jarvis-weather-brain-logging`, mergiato in main)

Su richiesta di Alessandro (JARVIS "come un sistema operativo": webcam+battuta
occhiali, ora, meteo, check TradeFlow, più "sistema tutto cio' che non
funziona" e "ogni interazione aggiorna il grafo Obsidian"). Verificato che
webcam/battuta napoletano/controllo OS/riconoscimento volto/ora erano già
implementati e intatti (blocchi v3 precedenti) — non ricostruiti.

- **`core/weather.py`** (nuovo): Open-Meteo + fallback IP-geolocation, nessuna
  API key, cache 20 min. Iniettato nel system prompt come data/ora, in
  entrambi `core/claude_bridge.py` e `core/claude_api.py`. Override:
  `JARVIS_WEATHER_LAT/LON/CITY`.
- **`core/brain.py::log_interaction()`** (nuovo): un nodo per giorno+workspace
  (non uno per domanda) bump-ato ad OGNI interazione — comandi rapidi di
  `core/intents.py` inclusi (prima non toccavano mai il second brain, zero
  passaggio da Claude). Wired in `claude_bridge.run_claude()`,
  `claude_api.run_voice()`, `intents.execute_intent()` (nuovi parametri
  `workspace`/`raw_text`, propagati da bot.py/web_bridge.py/daemon.py).
- **Bug fix**: `claude_api.run_voice()` non chiamava mai
  `brain.extract_and_store()` — un blocco ```brain``` emesso durante una
  risposta vocale sarebbe stato letto ad alta voce come JSON grezzo. Corretto
  e, su richiesta esplicita di oggi, la voce ora SCRIVE nel second brain
  (superata la decisione "sola lettura" del 2026-07-15).
- **Bug fix**: `brain.fetch_context()`/`extract_and_store()` chiamavano
  `_bootstrap()`/Turso senza try/except — un blip di rete transitorio (vedi
  [[network-quirks-this-pc]]) faceva fallire l'intera risposta a Claude
  invece di degradare silenziosamente. Ora tornano un default sicuro su
  qualunque eccezione — il second brain resta un arricchimento, mai un
  requisito per rispondere.
- Verificato con chiamate reali (non mock): meteo live → "32°C, cielo sereno,
  vento 12 km/h (Palma)"; nodo + nota Obsidian creati per davvero su Turso/
  vault veri. 41/41 test passano (17 nuovi: `tests/conftest.py` con guardrail
  che disabilita Turso/vault reali nei test — questa macchina ha credenziali
  vere in `.env`, senza guardrail i test avrebbero scritto dati finti nel
  second brain/vault di produzione).
- **Non verificato dal vivo** (richiede lui): "che meteo c'è" a voce reale,
  grafo dashboard che mostra il nodo "Interazioni ws — data" crescere ad ogni
  scambio nel browser vero.
- TradeFlow AI controllato (sola analisi, JARVIS non tocca quel repo): bot
  fermo dal 2026-07-10 (bug reale, fix scritto ma non deployato + serve
  restart VPS) e cron giornaliero fermo da una settimana — dettagli in
  `memory/projects/tradeflow-ai.md`.

## JARVIS v4 — always-on, voce streaming+GPU, stato progetti (2026-09-14, branch feature/jarvis-autostart + feature/jarvis-voice-streaming + feature/jarvis-project-status, mergiati in main)

Sessione ripresa dopo ~2 mesi di pausa (ultimo log 2026-07-16). Richiesta di
Alessandro: JARVIS "vero concetto di Iron Man" — usa la sua macchina,
risponde in fretta a comando vocale, verifica stato progetti, e altro.
Verificato a inizio sessione: v3.1 intatto ma bot.py/daemon vocale
entrambi SPENTI (nessun processo attivo) — avviati a mano. Piano approvato
in Plan Mode a blocchi. Tentata prima esecuzione con 3 subagent fork
paralleli su worktree isolati — tutti e 3 falliti a meta' per rate limit
di sessione (429, reset 20:30 Europe/Rome). Due worktree avevano gia'
scritto un file completo ciascuno prima di fallire (setup_autostart.ps1,
core/project_status.py) — salvati e riusati invece di ricostruire da
zero; il terzo (voce) non aveva scritto nulla, ricostruito direttamente.

**Blocco A — avvio automatico** (`setup_autostart.ps1`/
`uninstall_autostart.ps1`): due Scheduled Task (`\JARVIS\Bot`,
`\JARVIS\VoiceDaemon`), avvio a ogni logon, nessuna finestra (wrapper
`.vbs` -> `pythonw.exe` dentro `cmd /c ... > logs\*.log 2>&1` — senza il
redirect, `sys.stdout is None` di un processo GUI-subsystem farebbe
esplodere `daemon.py` all'avvio contro `sys.stdout.reconfigure(...)`),
restart automatico se crasha (5 tentativi/2min), flag batteria
(portatile). Registrato ed eseguito dal vivo con successo — connessione
TLS reale a Telegram (149.154.166.110:443) confermata per il processo
lanciato dal task.

**Limite scoperto sul campo, non una scelta progettuale**: da una sessione
Claude Code (stesso utente Windows, stessa sessione, verificato) NON si
riesce a terminare un processo lanciato da uno Scheduled Task — "Accesso
negato" sia con `Stop-Process` che `taskkill` che (silenziosamente)
`Stop-ScheduledTask` sui processi orfani sotto `pythonw.exe`. Owner e
SessionId combaciano esattamente con quelli della sessione Claude Code
stessa — non e' un problema di utente/sessione diversi. Causa quasi certa:
EDR aziendale (macchina nel dominio `IVECOEUROPE`) o una restrizione del
token di questa sessione di automazione. **Conseguenza pratica**: dopo
QUALSIASI modifica a bot.py/daemon una volta che l'autostart e' attivo, se
il processo vecchio e' gia' in esecuzione, farlo ripartire con il codice
nuovo richiede o un vero logoff/riavvio di Windows o che Alessandro lo
chiuda lui stesso (Task Manager, ha accesso pieno) — una sessione Claude
Code da sola non ci riesce piu' una volta che il task e' partito. Successo
in questa sessione (2026-09-14): il vecchio bot.py e' rimasto sul codice
pre-merge (impossibile far ripartire); VoiceDaemon invece e' ripartito
pulito col nuovo codice perche' non stava gia' girando quando il merge e'
avvenuto.

**Blocco B — voce streaming + GPU** (`core/claude_api.py`,
`core/voice/tts.py`, `core/voice/daemon.py`, `core/voice/stt.py`):
`run_voice_streaming()` sostituisce la chiamata bloccante — Claude genera
via `client.messages.stream()`, JARVIS inizia a parlare dalla prima frase
pronta (regex split su `.!?`/newline) invece di aspettare tutta la
risposta; si ferma di colpo a parlare appena vede l'inizio di un fence
```` ``` ````: i blocchi ```brain```/```browser```/```system``` restano
SEMPRE fuori dall'audio (il testo completo continua ad accumularsi
invariato per l'estrazione a valle) — stesso rischio del bug "JSON letto
ad alta voce" gia' capitato una volta (2026-07-16), qui strutturalmente
impossibile. `tts.py::speak_stream()` sintetizza la frase N+1 (edge-tts
via websocket, gia' capace di streaming — prima sfruttato solo per il
salvataggio su file intero) mentre la N sta suonando, coda `asyncio.Queue`
apposta NON limitata (una `maxsize=1` sembra piu' "naturale" per un
lookahead di una frase sola ma rischia il deadlock se il consumer esce
mentre il producer e' bloccato su `queue.put()`). Interruzione (hotkey/
wake word mentre JARVIS parla) confermata ancora funzionante, ora piu'
granulare (per frase, non piu' per l'intera risposta). GPU: `stt.py` prova
`device="cuda"`, fallback automatico e loggato a `device="cpu"` —
**verificato dal vivo che il fallback scatta davvero su questa macchina**:
`RuntimeError: CUDA driver version is insufficient for CUDA runtime
version` — la NVIDIA T1200 c'e' ma non e' sfruttata finche' non si
aggiorna il driver NVIDIA (non fatto oggi, decisione sua). 63/63 test
verdi (7 nuovi, incluso un test dedicato che conferma che un fence ```
interrompe la voce ma non l'estrazione blocchi). **Non verificato dal vivo
in questa sessione**: audio/microfono reali (richiede la presenza fisica
di Alessandro) — pero' il VoiceDaemon gira gia' con questo identico
codice (vedi Blocco A), pronto per essere provato.

**Blocco C — stato progetti + digest mattutino** (`core/project_status.py`
nuovo, `bot.py`, `core/intents.py`, `core/web_bridge.py`): un solo punto
(`check_all()`+`format_report()`, riusato ovunque) richiamato da comando
Telegram `/progetti`, intent veloce testo/voce ("stato progetti"/"come
vanno i progetti" — necessario perche' il canale vocale non ha accesso
reale a strumenti, senza l'intent non potrebbe mai eseguire git per
davvero), e un digest mattutino opzionale (`JARVIS_DAILY_DIGEST_HOUR=8`,
loop interno a bot.py visto che ora resta sempre acceso). Riusa
`SystemExecutor.git()` gia' esistente (sola lettura: `status`/`log`,
nessun subprocess nuovo), incrocia con la sezione `## Stato` di
`memory/projects/<nome>.md` (testo grezzo, flag vocale solo se contiene
🔴). **Bug reale di configurazione trovato e corretto**: `WS_AURA` in
`.env` puntava a `conciergebookings`, cartella sparita da mesi (probabile
rename esterno a JARVIS durante la pausa di 2 mesi) — il repo vero e'
`auraibiza` (CLAUDE.md interno si autodescrive come Aura Ibiza). Corretto
anche in `JARVIS_ALLOWED_DIRS` (whitelist separata controllata da
`SystemExecutor.git()` — senza questo fix i controlli sarebbero comunque
rimasti bloccati dietro conferma). Verificato dal vivo sui 3 repo reali:
AURA/TradeFlow/WhiteSoul tutti puliti su `main`, flag "problema noto"
confermato per TradeFlow (bot ancora fermo dal 2026-07-10, non risolto
lato loro — vedi `memory/projects/tradeflow-ai.md`). Pannello dashboard
**rimandato su richiesta esplicita di Alessandro** (AURA/TradeFlow/
WhiteSoul non hanno un endpoint pubblico come TradeFlow — servirebbe prima
far scrivere a JARVIS uno snapshot su Turso, lavoro a parte non fatto).

**In sospeso, non costruito**:
- **Blocco D (Iveco)**: Alessandro vuole che JARVIS usi il browser per
  leggere pagine e capire cosa sta facendo su Databricks, interroghi
  Databricks Genie, risponda alle chat Microsoft Teams, apra/legga le
  mail Outlook. Segnalato il rischio reale (dati aziendali Iveco verso
  l'API Anthropic, non un tool aziendale approvato; automazione di sessioni
  SSO Teams/Outlook puo' violare policy IT o far scattare anti-abuse
  aziendale) e proposto un default: Genie via API con un suo token (in
  linea con quello che gia' fa li'), Outlook sola lettura, Teams sola
  lettura + bozze da approvare (MAI invio automatico a suo nome — stessa
  regola gia' sua per i clienti in CLAUDE.md, qui estesa ai colleghi).
  Chiesto esplicitamente se ha gia' verificato con IT/policy Iveco — non
  ancora risposto. **Nulla progettato ne' iniziato.**
- Chiesto e non ancora risposto: "deve rispondermi sempre vocalmente"
  significa anche le risposte testo/Telegram lette ad alta voce dagli
  altoparlanti del PC (oltre al canale vocale, che gia' parla sempre e
  oggi lo fa in streaming) — non costruito finche' non conferma, per non
  far parlare il PC a vuoto quando lui e' altrove o in un contesto
  d'ufficio.

**Da verificare dal vivo (richiede lui)**: chiudere il vecchio processo
bot.py (Task Manager o riavvio PC) perche' `/progetti`/digest/intent
prendano il posto del vecchio codice; un vero logoff/logon per confermare
il riavvio automatico end-to-end; "hey jarvis"/hotkey per sentire la voce
piu' reattiva dal vivo; il digest delle 8:00 di domani mattina.

**Stesso giorno, dopo**: confermato "sempre vocalmente" -> anche testo/
Telegram parla dagli altoparlanti PC (`bot.py::speak_locally()`, riusa
`/voce on|off` esistente, non un interruttore nuovo — vedi log 22:29).
Confermato IT/policy Iveco ok per il Blocco D, poi "procedi senza
approvazione": costruita la fase 1 — `core/databricks.py` (OAuth M2M +
Genie Conversation API, verificato contro la doc ufficiale; QAS
raggiungibile da Claude via blocco ```genie```, PRD solo da `/genie_prd`
+ conferma esplicita, mai automatico) e `core/screen_context.py`
(Teams/Outlook/schermo -> screenshot -> image_b64, stesso schema della
webcam). **Bloccanti per l'uso reale**: manca lo space_id del Genie Space
(Alessandro deve indicarlo — l'API lo richiede sempre, "Genie senza
spazio" non esiste); Teams/Outlook mai loggati nel browser persistente di
JARVIS (richiede un suo login manuale una tantum nella finestra visibile
che si apre). Mai un invio automatico su Teams/mail — solo bozze, per
scelta esplicita di sicurezza. Dettaglio completo in log 2026-09-14 22:29.

**Stesso giorno, ancora dopo**: mic della dashboard segnalato non
funzionante — testato dal vivo (claude-in-chrome), codice/permesso OK
nella sessione di test, ma Alessandro conferma che nel suo browser reale
il pulsante non cambia mai aspetto al click; ipotesi principale permesso
microfono bloccato nel suo Chrome, non confermato, resta un problema
aperto. Aggiunta voce->Telegram per iscritto (`core/telegram.py` +
`daemon.py::_notify_telegram()`). **Outlook ora e' via COM su Outlook
desktop** (`core/outlook.py`, `pywin32`), non piu' screenshot browser —
sola lettura, intent veloce "controlla la posta", verificato dal vivo
contro la sua Inbox reale. Dettaglio in log 2026-09-14 23:21.

**Stesso giorno, ultimo**: chiarito che "Genie Code" (assistente di coding
Databricks, ex Databricks Assistant) e' un prodotto diverso dall'AI/BI
Genie gia' costruito — nessuna API esterna, non automatizzabile.
Aggiunta invece la Statement Execution API di Databricks
(`core/databricks.py`, blocco ```dbsql```, sola lettura sempre, QAS di
default, PRD via `/sql_prd` + conferma). Verificato con query reale su
QAS. Dettaglio in log 2026-09-14 23:41.

**Stesso giorno, finale**: risolto il mic del dashboard sostituendo il
riconoscimento cloud del browser (irraggiungibile su questa rete) con
registrazione locale + trascrizione via faster-whisper (stesso motore
del daemon vocale). Non serve piu' la parola "Jarvis" prima del comando.
Deploy automatico confermato attivo sul dashboard reale. Richiede comunque
il riavvio del bridge locale per essere provato dal vivo. Dettaglio in
log 2026-09-14 23:59.

**2026-09-15**: segnalato che la trascrizione dashboard funzionava ma la
risposta non si sentiva mai, solo testo in console. Causa: `speak_locally()`
("sempre vocalmente", 22:29 del 14/09) era stata agganciata solo a
`bot.py` (Telegram), mai a `core/web_bridge.py` — il giro voce della
dashboard era STT-only fin dalla sua creazione. Estratto motore/pulizia/
interruttore condiviso in `core/voice/tts.py::speak_if_enabled()`, ora
chiamato da entrambi i bridge negli stessi punti (post-intent, post-
run_claude). Branch `fix/dashboard-tts-response`, mergiato e pushato su
main, 117/117 test verdi. **Non verificato dal vivo**: richiede riavvio
del bridge locale + un comando vocale reale dalla dashboard.

**Stesso giorno, dopo**: chiesto di eliminare il click per ogni comando
sulla dashboard — scelto l'ascolto a mani libere vero (non un hotkey) pur
sapendo del precedente negativo del 2026-07-14 (ascolto continuo del
vecchio riconoscimento cloud senza filtro → ~230 task spuri, ~1.33$ di
chiamate Claude reali). Riapplicata la stessa soluzione di allora ma
lato server invece che nel browser, perché la trascrizione ora avviene
in `core/web_bridge.py` (faster-whisper), non più via Web Speech API
client-side: `_strip_wake_word()` richiede "Jarvis" nella frase prima di
eseguire intent/task Claude, altrimenti la riga torna con status
"ignored" e la dashboard la rimuove senza mostrarla. `web/public/app.js`
`setupVoice()` riscritto da push-to-talk a "arma e resta armato" (loop
di segmenti auto-avviati/fermati dallo stesso rilevamento voce/silenzio
di prima). 123/123 test verdi (6 nuovi in `tests/test_web_bridge.py`),
mergiato e pushato su main. **Limite noto non verificato dal vivo**:
nessun pre-buffer prima della soglia di rilevamento — la prima sillaba
di "Jarvis" potrebbe risultare tagliata; da controllare con un test
reale, non affrontato oggi per tenere il diff minimo. **Non verificato
dal vivo**: richiede riavvio del bridge locale + prova reale col
microfono.

**Nota per sessioni future**: il commit/push di stasera e' stato bloccato
una volta dal classificatore di sicurezza di Claude Code per un messaggio
di commit troppo dettagliato sul contesto di rischio — messaggi di commit
piu' brevi e fattuali risolvono, non serve toccare i permessi.

## JARVIS v5 — testo/Telegram/dashboard sull'API diretta (2026-09-15, branch feature/text-channel-direct-api, mergiato in main)

Segnalata lentezza delle risposte testo/dashboard. Spiegato il floor
noto (~11-12s, avvio del processo `claude -p`) e il trade-off di passare
all'API diretta (perdita di Read/Write/Bash nativi). Risposta di
Alessandro: "per me va bene passiamo all'api se è più veloce e se serve
implementiamo tutte le cose che servono". Pianificato in Plan Mode data
la portata (motore centrale).

**Cambio**: `core/claude_bridge.py::run_claude()` e' ora un dispatcher.
Default: `_run_claude_api()`, nuovo motore che chiama l'API Anthropic
diretta (Sonnet 5, `JARVIS_TEXT_MODEL`) con un loop agentic manuale
(non Tool Runner beta) e 4 tool reali — `read_file`/`write_file`/
`list_dir`/`run_command` — appoggiati a `core/system_executor.py`
(whitelist + conferma `/confirm` gia' esistenti, non bash/text-editor
grezzi di Anthropic). Whitelist git ampliata per l'occasione: `checkout`/
`switch`/`merge` auto-eseguiti, **`git push` resta SEMPRE dietro
conferma esplicita** (unica barriera di codice, non solo di prompt, per
la regola "mai push diretto su main" di CLAUDE.md). Il workspace
**"trading" resta su `claude -p`** (serve il server MCP TradingView, non
raggiungibile dall'API diretta) — unica eccezione. Ripiego manuale
`JARVIS_TEXT_ENGINE=cli` in `.env` per tornare al comportamento
precedente senza toccare codice.

La pipeline di post-processing (blocchi ```brain```/```browser```/
```system```/```genie```/```dbsql```) era gia' condivisa e identica tra
CLI e canale vocale API (`core/claude_api.py`) — pura estrazione di
testo, non tool reali — quindi non ha richiesto modifiche, solo
fattorizzata in `_run_post_processing()` riusata da entrambi i motori
testo. History persistita in `state.json` sotto una chiave nuova
(`api_sessions`, testo pulito — mai i turni intermedi di tool_use/
tool_result — troncata alle ultime 8 coppie utente/assistente), separata
dal vecchio `sessions` (session_id opaco, resta per il motore CLI).

151/151 test verdi (25 nuovi: `tests/test_claude_bridge.py`,
ampliamento `tests/test_system_executor.py`). **Verificato dal vivo con
chiamate reali** (non solo mock/test): `read_file` reale su
`memory/profile.md` -> risposta corretta ($0.026); "che ore sono e che
tempo fa" -> risposta in ~1-2s di latenza reale della chiamata API
(contro l'11-12s+ del processo CLI). Piano completo salvato in
`C:\Users\f45038c\.claude\plans\splendid-herding-sutherland.md`.

**Non ancora verificato dal vivo**: un task reale da Telegram/dashboard
(richiede il solito riavvio del bridge locale), un flusso git completo
guidato da Claude (branch → modifica → commit → merge in locale →
verifica che un eventuale push chieda comunque conferma), il
comportamento con un errore API vero (rate limit/auth — oggi si affida
al catch-all generico gia' esistente in bot.py/web_bridge.py).

**Gap noto, accettato**: nessun bridging MCP (TradingView) per il nuovo
motore — chi chiede dati TradingView da testo/dashboard FUORI dal
workspace "trading" non li ha (gia' cosi' anche prima, non una
regressione introdotta oggi).

## Promemoria calendario Outlook (2026-09-16, branch feature/outlook-calendar-reminders, mergiato in main)

Richiesta esplicita di Alessandro: usare il calendario Outlook e avvisare
15 minuti prima dei meeting. `core/outlook.py` esteso con lettura
calendario via COM (olFolderCalendar, `IncludeRecurrences=True` + `Restrict`
sulla finestra temporale — stesso pattern retry/thread-fresco gia' in uso
per la posta). `bot.py::calendar_reminder_loop()` (nuovo task in `main()`,
poll ogni 60s) avvisa su Telegram + voce quando un evento entra nella
finestra (`JARVIS_CALENDAR_REMINDER_MINUTES`, default 15, 0 disattiva),
dedup in-memory senza persistenza (accettato: un riavvio del bridge puo'
far ripetere un promemoria recente, rischio trascurabile). Aggiunto anche
un intent on-demand ("che meeting ho oggi"/"agenda di oggi", vedi
`CALENDAR_INTENT_RE`). Verificato dal vivo: lettura reale del calendario
Outlook di Alessandro (trovato l'evento vero delle 10:05) e intent
completo via `parse_intent`/`execute_intent`. 227/227 test verdi.
**Non verificato dal vivo**: il loop always-on nel processo bot.py reale
(richiede il riavvio del bridge locale per caricare il nuovo codice).

## Pill workspace rimosse dalla dashboard, brain unificato (2026-09-16, branch feature/unify-workspace-brain, mergiato in main)

Richiesta esplicita di Alessandro: non vuole piu' vedere le pill progetto
(jarvis/aura/whitesoul/trading/isabela/vino) in cima alla dashboard, ne'
il grafo second brain segmentato/attenuato per workspace attivo — vuole
un brain unico che si popola man mano. Chiarito prima (le pill non erano
solo estetiche, sceglievano anche il repo/cwd su cui JARVIS opera) e
scelto con lui: auto-detect del progetto dal testo del task, non piu'
selezione manuale.

`core/claude_bridge.py::detect_workspace()` (nuovo, parole chiave per
progetto, default "jarvis") usato in `core/web_bridge.py::poll_web_queue()`
per la dashboard — il bot Telegram resta sul comando esplicito `/ws`
(`state["ws"]`), non toccato. `core/web_bridge.py::_push_result()` scrive
indietro il progetto rilevato sulla riga Turso (parametro `workspace`
opzionale) cosi' la dashboard puo' ancora mostrarlo (HUD "Progetto",
sola lettura ora, e tag nella cronologia task) senza che l'utente lo
scelga a mano. Rimossa la barra pill (`web/public/index.html`, `app.js`,
`style.css` — `.ws-pills`/`.ws-pill` morti, `header-clock` ora con
`margin-left:auto` per tenere clock/logout a destra senza lo spacer
`flex:1` che le pill fornivano). Grafo second brain: un solo colore per
tutti i nodi (`BRAIN_NODE_COLOR`, accent fisso #3987e5 — vedi
[[feedback-dashboard-accent-color]]) al posto della palette per-workspace
con dimming dei nodi fuori dal workspace attivo (probabile causa
principale del fastidio segnalato, non solo le pill in se').

237/237 test verdi (10 nuovi). **Non verificato dal vivo nel browser
reale**: serve il login della dashboard (password non presente in questo
ambiente/.env locale) — da controllare dopo il deploy che l'header non
abbia buchi di layout e che un messaggio tipo "controlla aura" venga
instradato davvero sul progetto giusto.

## "Vero Jarvis" — 5 feature in un colpo solo (2026-09-16, branch feature/jarvis-five-features, mergiato in main)

Su richiesta di Alessandro ("cosa possiamo implementare ancora da vero
Jarvis" -> 5 proposte -> "facciamo tutti e 5"). Dettaglio completo nel log
delle 11:53. Riassunto stato/config per sessioni future:

- **Briefing mattutino** (`core/briefing.py`): `/buongiorno` su Telegram +
  intent vocale/testo, sostituisce il digest mattutino di prima
  (`JARVIS_DAILY_DIGEST_HOUR` invariato come trigger orario). Verificato
  dal vivo con dati veri (meteo/calendario/mail).
- **Presenza proattiva** (`core/presence.py`): **disattiva di default**
  (`JARVIS_PRESENCE_INTERVAL_SEC` vuoto) — va accesa esplicitamente in
  `.env`, attiva la webcam periodicamente. Non ancora accesa qui.
- **Bozze mail/Teams**: Outlook via `core/outlook.py::create_draft_email()`
  (verificato dal vivo, vedi log) sempre attivo, nessuna config richiesta.
  Teams via browser richiede che Alessandro faccia il login UNA TANTUM
  nella finestra Playwright di JARVIS (limite gia' noto da prima, non
  nuovo) — finche' non lo fa, Claude ripiega sulla vecchia bozza scritta
  a parole.
- **Dashboard trading** (`core/myfxbook.py`): richiede `MYFXBOOK_EMAIL`/
  `MYFXBOOK_PASSWORD` in `.env` (non ancora impostate) — finche' mancano,
  intent/briefing/pannello dashboard restano silenziosamente disattivi.
  Unica fonte finanziaria collegata per scelta esplicita sua (2026-09-16):
  AURA/WhiteSoul/AP Systems non hanno ancora un posto strutturato da cui
  prendere i ricavi (ConciergeFlow ha un modulo contabilita' vero ma
  `JARVIS_ALLOWED_DIRS` punta al clone sbagliato/stale — da sistemare se
  in futuro si vuole aggiungere anche quello).
- **EnvironmentRouter Iveco**: nuova voce `iveco` in `WORKSPACES` (env
  `WS_IVECO`, vuoto = nessun path locale ma il routing/rilevamento dal
  testo funziona comunque). Genie/dbSQL restavano gia' disponibili sempre
  a prescindere dal workspace — questa voce serve solo per file/comandi
  e second brain quando si parla esplicitamente di lavoro Iveco.

**Non verificato dal vivo** (richiede lui): saluto automatico webcam,
bozza Teams reale (serve prima il suo login nel browser JARVIS), pannello
trading (serve prima `MYFXBOOK_EMAIL`/`PASSWORD`), un vero `WS_IVECO`.
271/271 test verdi.

## VS Code + Claude Code (2026-09-16, branch feature/vscode-claude-code, mergiato in main)

Richiesta esplicita: JARVIS deve poter aprire un progetto in VS Code e
delegare una modifica vera a una sessione REALE di Claude Code (il CLI),
non solo ai 4 tool limitati del motore API di JARVIS. `core/
system_executor.py::open_vscode()` + `core/vscode_actions.py` (blocco
```vscode```, comando Telegram `/code <progetto> <prompt>`). Ambito
volutamente ristretto ai `WORKSPACES` gia' noti/autorizzati (scelta
esplicita sua) — niente path arbitrari. Esecuzione sempre in un thread di
sfondo, mai bloccante: il risultato arriva su Telegram, non nella
risposta immediata (un task di coding vero puo' richiedere minuti).
Verificato dal vivo: VS Code aperto per davvero sul repo `jarvis`, e una
vera sessione Claude Code CLI lanciata con un prompt vincolato ("non
modificare nulla") — nessuna scrittura reale (verificato `git status`
invariato), notifica Telegram formattata correttamente. 284/284 test
verdi. **Non ancora provato con un vero task di modifica codice** — la
prima volta va guardata con attenzione.

**Problema aperto, non risolto**: uso reale da dashboard riporta "errore
launch codice 18" quando apre VS Code. Il log del vault conferma che
`open_vscode()` (Popen) riesce sempre lato JARVIS — l'errore arriva DOPO,
da VS Code/Windows/EDR, testo esatto non ancora noto. Vedi log
2026-09-16 pomeriggio.

## Fix pomeriggio (2026-09-16, branch fix/calendar-stop-outlook-browser, mergiato+pushato in main, commit e25226a)

3 bug reali trovati analizzando `logs/bot.log` di uso vero (non test):
- **Calendario "domani"**: `CALENDAR_INTENT_RE` troppo rigido (richiedeva
  "ho"/"ci sono" letterali) cadeva su STT imperfetta -> la domanda finiva
  su Claude (motore API diretto), che non ha NESSUN accesso al calendario
  (solo `core/intents.py` lo interroga via COM) -> "non posso
  collegarmi" anche se il calendario esiste dal mattino. Fix: regex piu'
  permissivo + `outlook.get_events_for_day_sync()` (finestra sul giorno
  solare, non piu' relativa a "ora").
- **"Jarvis stop"**: non era un intent riconosciuto -> dopo l'interruzione
  del TTS in corso (barge-in gia' esistente), "stop" veniva comunque
  passato a Claude, che rispondeva e JARVIS ricominciava a parlare. Fix:
  intent `"stop"` dedicato, mai spedito a Claude, mai pronunciata la sua
  conferma.
- **Outlook nel browser**: `browser.read()` = `inner_text("body")` su
  Outlook Web tornava ribbon+cartelle+anteprime+corpo mail tutti
  concatenati, letto ad alta voce parola per parola. Fix: lettura mirata
  via ruoli ARIA `"document"`/`"option"` (indipendenti dalla lingua UI) +
  nuova azione ```browser``` `{"action":"read_mail","count":N}` che apre
  N mail in sequenza e ritorna solo il corpo di ciascuna.

297/297 test verdi (12 nuovi). **Non verificato dal vivo**: la lettura
mirata Outlook Web (nessuna sessione OWA reale raggiungibile da questa
sessione — selettori ARIA testati solo con mock, da controllare alla
prima "leggi le mail nel browser" reale dopo il riavvio del bridge).
Bridge locale (bot.py/VoiceDaemon) va riavviato per caricare questo
codice — in esecuzione dalle 13:10, precede il merge.

## Fix pomeriggio parte 2 (2026-09-16): meteo "domani" + bug reale Teams/schermo

- **Meteo "domani"**: stesso pattern del calendario — intent troppo
  stretto ("che tempo fa" solo presente/oggi) e nessun dato di previsione
  mai raggiungibile da una domanda (`get_weekly_forecast()` esisteva gia'
  ma solo per il pannello dashboard). Fix: regex piu' permissivo +
  `weather.format_tomorrow_line()`.
- **Bug reale, serio**: leggere Teams/schermo (immagine allegata a Claude)
  non ha MAI funzionato dal 2026-09-14 — `media_type` sempre hardcoded a
  "image/jpeg" (corretto per la webcam, sbagliato per gli screenshot PNG
  di `core/screen_context.py`), l'API Anthropic rifiutava sempre con un
  400. Fix: sniffing sui byte magici (`claude_bridge._detect_image_media_type`).
  Aggiunto anche `BrowserAgent.screenshot(scoped=True)` (ritaglio sulla
  regione ARIA "main" quando c'e', per Teams) su richiesta di filtrare
  l'interfaccia dalla risposta.
- 316/316 test verdi. **Non verificato dal vivo**: nessuna sessione Teams
  reale raggiungibile da qui per confermare che il crop tolga davvero il
  rumore visto da Alessandro.

**Flusso interattivo mail/Teams + stato progetti senza percentuali** —
mail/Teams: nuovo flusso "non lette o tutte? -> elenco -> quale? -> apri e
riassumi" (tool `list_emails`/`read_email` in `core/outlook.py`/
`core/claude_bridge.py`, SYSTEM prompt aggiornato; Teams via i primitivi
```browser``` read/click gia' esistenti, pagina persistente tra i turni).
Rimosso il fast-path `core/intents.py` per "leggi le mail" (restava solo
il conteggio non lette) e per "stato progetti" generico (ora chiede quale
progetto, tool `get_project_status`). Rimosso `health_percent` (punteggio
sintetico mai piu' necessario dopo GitHub/Vercel reali) da backend e
dashboard. 325/325 test verdi. Non verificato dal vivo.

**Meteo: tool `get_weather_forecast` invece di ricerca browser** — il
fast-path di `core/intents.py` copriva solo oggi/domani; per ogni altro
giorno Claude non aveva alternativa e apriva un browser. Aggiunto
`weather.format_day_line(days_ahead 0-6)` + tool nativo
`get_weather_forecast` (stesso pattern di `recall_memory`), SYSTEM prompt
aggiornato per vietare esplicitamente la ricerca browser per il meteo.
320/320 test verdi. Non verificato dal vivo.

**Ricerca (non implementata)**: guardato github.com/FatihMakes/Mark-LIII
su richiesta di Alessandro per idee. Spunti concreti non ancora costruiti
in JARVIS: memoria "on-demand" (solo core+fatti recenti nel prompt, resto
cercato a richiesta, invece di iniettare sempre tutto il second brain) e
undo reversibile per azioni distruttive (file/scritture). Chiesto ad
Alessandro quale dei due priorizzare, non ancora risposto.

## Audit voce (2026-09-17)

Ridotta la pausa post-parlato della registrazione da 1200 a 800 ms e
configurato faster-whisper con `beam_size=1` e senza contesto del segmento
precedente: ottimizzazione per comandi brevi sul fallback CPU. Tuning
reversibile: `JARVIS_SILENCE_HANG_MS` e `JARVIS_WHISPER_BEAM_SIZE` nel
`.env`. Test mirati: 60 verdi. Da verificare dal vivo dopo il riavvio di
VoiceDaemon e bridge locale; se la precisione non basta, alzare il beam a 2
o 5. GPU ancora non utilizzabile per driver NVIDIA incompatibile.

## Fix timeout bridge (2026-09-18)

Risolti i task dashboard abbandonati in stato `running` quando il bridge
locale viene terminato o riavviato: `core/web_bridge.py::recover_interrupted_tasks()`
li marca esplicitamente `error` all'avvio del poller, invece di lasciare la
dashboard in polling per cinque minuti. Puliti anche tutti i task orfani gia'
presenti in Turso. Corretto anche `setup_autostart.ps1`: il VBS nascosto ora
lancia `python.exe`, non `pythonw.exe`, perche' Task Scheduler resti agganciato
al processo e applichi il restart-on-failure. Il processo `bot.py` corrente e'
quello precedente al fix: per caricarlo serve chiuderlo da Task Manager e
rilanciare `\\JARVIS\\Bot`.

## Fix voce/coda/dashboard (2026-10-12, branch fix/voice-queue-and-stt, mergiato in main)

Hotkey Ctrl+Alt+J rotta dal 2026-09-15 (int16 al VAD silero, ora float32).
Coda web: comandi certi prima, audio in ordine di arrivo, solo un comando
vero supera gli altri (prima il rumore uccideva pulsanti e testo scritto);
audio stantio scade dopo 30 s; "Jarvis" + pausa + comando ora funziona.
Una sola scheda dashboard tiene il mic (Web Locks). API non manda piu'
audio/immagini al browser — cronologia da 31,5 s/12 MB a 0,38 s/20 KB.
Audio in Turso: puliti i 1,26 GB storici, il bridge tiene solo gli ultimi
5 (`JARVIS_AUDIO_KEEP`) a ogni task chiuso; indici `idx_tasks_status_created`
e parziale `idx_tasks_audio` creati all'avvio. Dettaglio in log 2026-10-12.
Non verificato dal vivo: serve riavvio di bot.py e VoiceDaemon.

## Latenza risposte (2026-10-12, branch perf/faster-replies, mergiato)

Claude via API diretta risponde in 1,2-1,6 s: non e' il collo di bottiglia.
Il tempo va in whisper su CPU (4-5 s a frase, small), poll coda, contesto
meteo+brain (1,4 s) e TTS. Applicati: whisper 8 thread + beam 5, poll 1 s,
prompt caching (input -68%), retry edge-tts sul 403 casuale (workaround).
Blocco principale rimasto: GPU T1200 inutilizzabile con driver 517.13 e
runtime attuale. Verificare insieme driver, CUDA/cuBLAS e cuDNN compatibili.
Il WER riportato sopra riguarda un benchmark sintetico, non la voce reale
di Alessandro. Latenza e precisione sulla T1200 non sono state misurate:
non promettere large-v3-turbo sotto il secondo, soprattutto con 4 GB VRAM.

## iPhone e percorso a bassa latenza (2026-10-13)

Alessandro ha scelto la trascrizione locale sul PC, non un provider STT
cloud. Attenzione: attualmente gli audio della dashboard passano comunque
da Vercel/Turso; per mantenerli solo sui dispositivi serve un collegamento
diretto autenticato e cifrato. Claude via API resta il motore delle risposte.

Branch `codex/ios-local-voice`: layout mobile a pannello singolo, safe area,
tastiera via visualViewport, controlli 44 px, dock scorrevole, microfono su
tap, resume AudioContext nel gesto utente, annullamento permessi/interruzioni
senza riaccensione tardiva. Silenzio browser ridotto da 1200 a 800 ms.
Animazione orb fermata su mobile/background. 18 test Chromium/WebKit con
API e media simulati passati; non verificato su iPhone fisico.

Per il quasi immediato resta da implementare il percorso persistente
iPhone-PC con trascrittore caldo/GPU compatibile, streaming Claude e audio
per frasi sul dispositivo chiamante. Ora la dashboard usa messages.create
e riproduce il TTS sul PC: lo streaming del daemon nativo non è quello web.
Nessuna modifica a driver, STT provider o instradamento audio in questo branch.

## Collegamento privato voce attivo (2026-10-13)

Su «fai tutto committa e pusha», implementato `core/live_server.py` con
WebSocket autenticato, STT locale gia' caldo e audio delle risposte sul
dispositivo chiamante. Dashboard privata Tailscale Serve HTTPS, bind solo
loopback 8765; porta privata 8443. Tailscale installato e PC collegato;
Alessandro conferma di vedere `tl0352132` nell'app iPhone. Il link iniziale
di login dava 403 sull'iPhone, ma la rete PC era gia' attiva: usare l'URL
dashboard, non il link di associazione.

URL locale a questa macchina: https://tl0352132.tail18e3c0.ts.net:8443/ .
Password separata nel file ignorato `.live-password`; config ignorata
`.live-config.json`. `setup_live.ps1 -Start` registra LiveBridge nascosto
all'accesso Windows e AudioCleanup ogni 5 minuti. `uninstall_live.ps1`
rimuove i due task senza terminare processi o eliminare dati.

Audio in ingresso solo in RAM, nessun passaggio Vercel/Turso e nessun
fallback cloud. Testo/immagini esplicite continuano verso Anthropic, testo
della risposta verso edge-tts; second brain mantiene i log testuali esistenti.
Haiku (`JARVIS_VOICE_MODEL`) con gli stessi tool, streaming per frasi, coda
TTS limitata, Stop/disconnessione scartano audio obsoleto. Rumore non
interrompe comandi validi. Contesto preparato ogni minuto, history privata
in RAM, nessuna scrittura allo state.json del bot. Trading conserva il CLI.

Login HTTPS/cookie Secure, WebSocket reale e STT caldo verificati sul PC.
Prova sintetica CPU small: ~2,05-2,25 s di STT; Haiku su una domanda breve
1,66 s al primo testo e 5,49 s al primo MP3 completo (TTS incluso, STT
escluso). Non e' una misura su iPhone fisico e NON e' quasi istantaneo.
Driver NVIDIA 517.13 ancora incompatibile con CUDA installato; nessun
driver sostituito. Il fallback CPU funziona. Serve upgrade driver/runtime
compatibile e misurazione con voce reale prima di promettere meno di 1 s.

Gli audio Turso erano risaliti a 10 con il vecchio bridge ancora in memoria:
ripuliti a 5 e verificato AudioCleanup con LastTaskResult=0. I pending/running
sono preservati. LiveBridge riavviato dopo chiusura manuale del vecchio PID
38936 da parte di Alessandro: Stop-ScheduledTask aveva lasciato il figlio
Python vivo. Bot/VoiceDaemon precedenti non terminati.

Verifica: 380 test della suite completa, piu' regressione aggiuntiva dello
Stop mentre un comando sostitutivo attende la fine di un'azione OS (suite
servizio 10/10). La cancellazione del chiamante non deve essere inghiottita
dal cleanup del vecchio turno, altrimenti la sostituzione puo' partire dopo
Stop. Alessandro ha chiuso anche il PID 13276: servizio finale riavviato e
login HTTPS/WebSocket con STT pronto verificati nuovamente. Codice commit
`206876b`, push su `codex/ios-local-voice`, SHA locale/remoto uguali.
WebKit sul vero URL HTTPS: login, stato voce pronta e logout verificati senza
errori JavaScript; il microfono hardware non e' disponibile nell'emulatore
Windows e resta da provare sull'iPhone fisico.

## Assistente unico e fonti operative (2026-10-13)

Alessandro vuole una conversazione unica, progetti riconosciuti automaticamente,
analisi/statistiche e aiuto con priorita' lavorative e personali. Fonti indicate:
Outlook, file, progetti sul PC, Databricks (dashboard/notebook/job).

Branch `codex/unified-assistant`: core/projects.py scopre repo immediatamente
sotto la radice, note e WS_*. .project-catalog.json permette altre radici e
cartelle non Git (IVGAgent registrato). Trovati 16 progetti, senza concedere
nuovi permessi di scrittura; lettura file testuali protetta entro la cartella.
Panoramica privata aggiornata dal PC, cache 30 s. UI senza pannelli fissi per
TradeFlow/social; tre suggerimenti nella conversazione, mobile verificato.

Sessione privata condivisa tra progetti (8 scambi), contesto precedente per
follow-up e comandi rapidi. Sonnet per analisi/coaching/pianificazione, Haiku
per richieste brevi; TradingView esplicito usa CLI. Outlook offre agenda e
conteggi reali. Focus personali/lavorativi solo su richiesta esplicita, SQLite
locale ignorato da Git. Tempo calendario calcolato senza sovrapposizioni,
inclusi eventi gia' iniziati, mai presentato come produttivita'.

Databricks QAS: 31 job e 16 dashboard AI/BI visibili nella verifica; strumenti
GET per inventario, definizioni dashboard, notebook richiesti e run. Pagine
run da 25, metriche esplicitamente parziali e con denominatore. SQL nativo
consente interpretazione dopo lettura dei risultati, con guardia anche su
WITH seguito da DML. PRD resta sul percorso di conferma preesistente.
Genie Space ID assente: non necessario per questi tool. Niente indice globale
PDF/Excel/mail o accesso automatico al contenuto dei progetti cloud.

Prova reale Sonnet/tool corretta in 4,47 s senza log nel second brain. Suite
398/398 e successivi 55 test mirati SQL/tool passati. WebKit HTTPS reale
login/logout e UI senza errori; microfono fisico iPhone non verificabile qui.
Al momento della chiusura del codice il vecchio LiveBridge e' ancora in RAM:
serve una sola chiusura manuale da parte dell'utente, poi avvio e verifica.

Codice `c9d51d1` pushato e verificato su `origin/codex/unified-assistant`.
Richiesta chiusura manuale del solo python.exe PID 14968 per caricare tutte
le modifiche in un unico riavvio. Finche' non confermata, backend nuovo non
ancora attivo; UI statica gia' visibile al reload. Test panoramica Outlook
reale (inclusione eventi iniziati prima del giorno) riuscito senza errori.

Attivazione completata il 2026-10-13 alle 16:30 (Europe/Rome): dopo la
conferma di chiusura del PID 14968, porta libera e LiveBridge avviato. Verifica
reale HTTPS/login/WebSocket riuscita; STT pronto su CPU, catalogo dinamico
16 progetti inclusi EYRA, IVGAgent, TradePilot e VMScout. Il backend aggiornato
e' ora attivo; ricaricare la dashboard per usare la conversazione unica.

## Correzioni Rete/meteo e voce essenziale (2026-10-13)

Rete restava su attesa perche' setConn era chiamato solo dal widget TradeFlow
rimosso. Ora WebSocket reale nel privato, API nel cloud; eventi di socket
precedenti non possono riportare offline una connessione nuova. Meteo aveva
7 giorni validi ma il titolo desktop finiva sotto l'header: pannello entro
viewport, aperto di default desktop, dal dock su mobile. Modifiche statiche
verificate sul vero HTTPS senza riavvio server.

Richiesta di Alessandro: non elencare tutti i progetti a voce, solo punti
salienti/attenzioni e meno attesa. Git parallelo e cache unica 30 s condivisa
tra tool e widget. Panoramica generica senza LLM: massimo due punti da
verificare, segnalazioni storiche esplicite e modifiche locali non confuse
con guasti. Dettagli/analisi/elenco completo restano richiedibili. Misura:
9,17 s prima, 1,59-2,22 s per scansione parallela, 31-47 ms snapshot, 63 ms
risposta a caldo (2 frasi, esclusi STT/TTS). STT CPU e TTS restano fattori
separati: niente promessa di risposta vocale istantanea.

413 test della suite completa e 42 mirati finali passati. Backend precedente
ancora PID 26352 alla chiusura del codice: nuova sintesi/cache richiedono
chiusura manuale e riavvio dopo commit/push; Rete/meteo disponibili al reload.

Attivazione completata il 2026-10-13 alle 17:12 (Europe/Rome): utente chiude
PID 26352, porta libera, LiveBridge avviato con PID 43472 e codice `effa55d`.
HTTPS e STT locale CPU pronti, 16 progetti. Panoramica reale produce 2 frasi,
26 parole e zero chiamate LLM; primo testo 63-78 ms con snapshot recente.
Meteo e Rete online riconfermati in WebKit mobile/desktop, nessun errore JS.
TTS ancora variabile: prima prova 4,5 s al primo audio e una frase fallita;
seconda prova completa senza avvisi, primo audio 2,797 s. Non confondere il
tempo testo con risposta vocale completa: STT e microfono iPhone esclusi.

## Memoria, TradePilot, DevOps e sfera mobile (2026-10-13)

Branch `codex/unified-assistant`. Memoria SQLite locale: comandi diretti senza
LLM, apprendimento selettivo con citazioni/fonte/data, correzioni prioritarie,
esclusioni prima di testo/TTS e lista disattivabile nel Second brain. Test
reale Haiku: fatto appreso dal messaggio e ricordato in conversazione nuova.
Esempi ipotetici dell'utente non applicati alla memoria reale.

Panoramica unica: equity TradePilot da VPS privata, saldo/drawdown, campioni
reali raccolti ogni minuto mentre LiveBridge e attivo, ricerche/statistiche
separate per modalita. Storico precedente non disponibile. 24 esperimenti
e 8 righe statistiche osservati; conto demo. Registro VPS distinto dal PC.

Azure DevOps collegato con Microsoft aziendale e Azure CLI, cache isolata.
Build, fasi pipeline, avvisi dei job, release e ambienti letti via GET. Prova
reale: run 20261013.11, Deploy to PROD succeeded (16:21 Roma), QAS skipped,
un warning nel job deploy. Nessun record ambienti/classic release: le fasi
della timeline sono necessarie. Non confondere succeeded build con deploy.

Sfera mobile: rimossa disattivazione su schermi piccoli; spazio sopra chat,
140px in verticale e 48px con viewport ridotta, 30fps e DPR massimo 1.5.
Pausa in background, immagine statica se il sistema richiede meno movimento.
In viewport ridotta nasconde i suggerimenti per lasciare spazio all'input.

Validazione: suite completa 441 test passati; dopo fix mobile 36 test UI
Chromium/WebKit passati, inclusa regressione riprodotta prima del fix.
WebKit sul vero HTTPS: sfera visibile, voce locale pronta, nessun errore JS.
JS syntax e diff check superati. Limite: iPhone fisico non provato dall'agente.

Backend nuovo da attivare con un solo riavvio dopo commit/push: vecchio
processo LiveBridge PID 43472 ancora attivo. Sfera/CSS disponibili al reload.
Procedura e configurazioni: `memory/playbooks/connected-memory-and-data.md`.

Attivato il 2026-10-13 alle 18:05 Europe/Rome: dopo chiusura PID 43472,
LiveBridge riavviato con PID 20396, codice `b841540`. HTTPS/login, WS/STT CPU,
API memorie, TradePilot e DevOps verificati sul servizio reale senza errori
delle fonti. TradePilot ora espone 25 esperimenti e 8 righe statistiche;
conto demo e curva con campioni reali. WebKit mobile sul vero HTTPS: sfera
visibile/animata, grafico equity, fasi PROD/QAS e pannello memorie disponibili,
nessun errore JS. Nessuna modifica al codice dopo il riavvio.

## Ascolto PC, Telegram e agenti coding (2026-10-13, 18:42)

Utente segnala entrambi i percorsi PC: dashboard "Ti ascolto" senza risposta,
wake word/hotkey non funzionanti. Bot e VoiceDaemon erano fermi, LiveBridge
attivo PID 20396. Microfono Windows apribile; modelli STT/wake word e hotkey
inizializzati senza errori nel preflight. Causa precedente uscita non isolata.

Dashboard privata: soglia RMS ridotta da .06 a .012, verificato inoltro voce
bassa .025 e scarto rumore .005/clic. Audio ignorato ora spiega di dire Jarvis.
Riprodotto inoltre HTTP 400 dopo tool streaming Anthropic: `parsed_output`
era reinviato all'API. Metadati SDK esclusi; test di regressione e due turni
API reali riusciti. Il daemon usa lo stesso Engine/memoria/tool della dashboard,
con event loop persistente.

Codex/Claude Code: apertura app sul progetto, prompt espliciti in background,
registro SQLite privato, stato/risposta in Panoramica e su richiesta vocale,
seguiti nella stessa sessione. Un lavoro per progetto; modifiche richieste e
cartelle autorizzate, niente bypass sandbox o deploy/push. Risultati Telegram
solo per lavori iniziati da Telegram. Non controlla automaticamente chat GUI
gia esistenti: traccia le sessioni CLI avviate da JARVIS.

Telegram: bot zerodayzz_bot verificato con getMe, senza webhook. Testo e note
vocali solo owner, STT locale, massimo 3 minuti/20 MB e pulizia temporanei.
Errori mascherati per non esporre il token; vecchi log bonificati. Credenziale
precedentemente esposta nei log da rigenerare tramite BotFather.

Validazione: 460 test completi passati, Chromium/WebKit inclusi; JS syntax e
diff check ok. App Codex e VS Code aperte sul progetto reale. Entrambi i CLI
verificati su fixture: lettura, scrittura di un solo file, ripresa sessione e
risposta coerente. Claude ha segnalato onestamente un permesso negato sul
profilo esterno alla fixture, pur completando il file richiesto.

Attivazione da completare dopo commit/push: Bot e VoiceDaemon possono essere
avviati direttamente perche fermi; LiveBridge richiede una sola chiusura
manuale del PID 20396. Prova con parlato reale ancora dell'utente.
Procedura: `memory/playbooks/voice-telegram-coding.md`.

Codice `5d17754` committato e pushato. Bot e VoiceDaemon avviati dai task e
verificati Running: processi effettivi 37196 (bot) e 8832 (voce), modelli
caricati su CPU e hotkey registrata. getMe conferma zerodayzz_bot operativo.
LiveBridge e ancora PID 20396: chiusura manuale richiesta una sola volta,
in attesa del "fatto". Script di verifica dopo il riavvio:
`.tmp/verify_voice_coding_ready.py` (API autenticata e audio sintetico completo),
`.tmp/verify_connected_ready.py` (fonti collegate). Nessun codice modificato
dopo l'avvio dei due servizi.

## Voce edge-tts 7.3.1 e meteo SVG (2026-10-14)

La voce era muta su tutti i canali: edge-tts 7.2.8 riceveva 403 su ogni
richiesta perché il servizio Microsoft ora vuole il token Sec-MS-GEC v2
(edge-tts 7.3.x). Il promemoria riunione è quindi arrivato solo su Telegram.
Requirements `edge-tts>=7.3.1`, venv aggiornato. Il retry su 403 resta.
Se la voce torna muta, controllare prima `logs/bot.log` per il 403 e la
versione di edge-tts su PyPI.

Meteo dashboard: icone SVG inline al posto delle emoji (`app.js::weatherIcon`,
mappatura WMO in `WX_KIND`). Pannello chiuso al boot desktop, si apre dal
dock o chiedendo il meteo. Su desktop 7 giorni su una riga, posizione
`--x:160px` per non coprire la conversazione. Commit a8fd9f0, merge b33d9f8.

Voce "vera" di JARVIS: trovati solo cloni community non licenziati di Paul
Bettany, solo inglese (Piper ONNX, RVC). Nessun modello italiano. Non
installati: clone di un attore vivente senza consenso, e RVC senza GPU
utilizzabile aggiungerebbe latenza.

## Voce film, pulsanti non interrotti, Databricks PRD (2026-10-14)

Voce: Andrew Multilingual in italiano + `core/voice/voice_fx.py::film`, scelta
da Alessandro tra campioni ascoltati (`.tmp/voci_jarvis/`). Variabili
`JARVIS_TTS_VOICE/RATE/PITCH/STYLE`. Dashboard: audio con effetti ricodificato
MP3 64 kbps.

Dashboard privata: nascondere la pagina non annulla più il comando sul PC
(prima `visibilitychange` → `cancel`, causa probabile degli "Interrotto." su
analisi lunghe). Il server logga sostituzioni e Stop.

Databricks: PRD leggibile in sola lettura per metadati job/run/dashboard.
`runs_summary` aggrega tutte le run del periodo nel codice (max 1000).
`compare_dashboards` abbina PRD e QAS per nome normalizzato e legge lo stato
/published. Requests Lakeview in serie per host con Retry-After (SSLError in
parallelo, 429 con richieste ravvicinate). SQL/Genie PRD restano su conferma.
Senza ambiente indicato, Alessandro intende PRD per i job.

## Sessioni aperte, voce italiana a caldo, XTTS opzionale (2026-10-14 pomeriggio)

`coding_tasks` include `open_sessions` (core/agent_sessions.py): sessioni
Claude Code/Codex aperte da Alessandro, dalla coda dei transcript locali.
Voce default Giuseppe + film. `.tts-voice.json` (non versionato) cambia
voce/stile/motore senza riavvii. Motore "xtts" (core/voice/xtts_server.py in
`.venv-xtts`, clip `jarvis_voice/refs`) pronto ma spento: su CPU 15-27 s per
frase. Diventa usabile con la GPU (driver NVIDIA aggiornato) o con
ElevenLabs. Il bot scrive in logs/bot.log una riga per ogni messaggio
Telegram ricevuto.

## Wake word solo con console aperta (2026-10-15)

Il daemon vocale non ascolta piu' in continuo: apre il microfono per la wake
word solo quando una console della dashboard e' aperta sul PC
(`core/console_presence.py`, file `.console-presence.json` scritto da
LiveBridge, WebSocket `?pc=1` solo da puntatore fine). A console chiusa resta
la hotkey Ctrl+Alt+J, senza stream aperto. `JARVIS_WAKE_WORD_MODE=always` per
tornare indietro. Verificato sul servizio reale. Merge da2e49d.

Aperta la domanda "JARVIS a PC spento": la parte personale (Telegram, API
Claude, memoria, progetti, TradePilot) puo' girare su una VPS; Outlook COM,
Teams, file locali e sessioni Claude Code/Codex restano legati al PC. Il
lavoro Iveco a PC spento richiede percorsi approvati dall'IT (app Graph nel
tenant, Databricks da IP esterno, oppure un Cloud PC aziendale).

## Apple Watch (2026-10-15)

Alessandro ha un Mac e un Apple Watch Ultra senza SIM (funziona via iPhone o
Wi-Fi conosciuto). Percorso scelto: prima Comandi Rapidi, poi l'eventuale app
watchOS nativa. `POST /watch/ask` su LiveBridge con token Bearer, verificato
dal PC via Tailscale. Da verificare: se il Watch raggiunge il tailnet tramite
l'iPhone. Procedura: `memory/playbooks/apple-watch-comandi-rapidi.md`.
App watchOS "quadrante" (sfera della dashboard, JARVIS e ora digitale dentro,
tocco per dettare) su branch `feature/watch-app`, guida `watch/README.md`. Non
ancora compilata (scritta su Windows): merge dopo il primo build sul Mac.
Quadrante Clockology senza Mac: video in loop della sfera
(`watch/tools/render_orb_video.py`, playbook `clockology-jarvis-face.md`).
Il 2026-10-16 la sfera originale e' stata rifiutata (non abbastanza rotonda):
inviati via Telegram gli stili `liscia` e `globo`, in attesa della scelta.
Lo stile scelto va portato anche in `OrbView.swift` dell'app nativa.

## Sfera rotonda, webcam LiveBridge, persona JARVIS (2026-10-16, branch feature/orb-camera-persona, mergiato in main d239b2d)

- **Sfera dashboard**: `web/public/orb.js` ha `ORB_STYLES` (`liscia` default,
  `globo`, `originale`); `createJarvisOrb(canvas, { style })`. URL
  `?orb=globo` per confronto. Il renderer video Clockology usa gli stessi
  stili (niente piu' patch del sorgente): una modifica a `orb.js` vale per
  dashboard e quadrante insieme.
- **Webcam**: `core/live_server.py::Engine.respond` cattura un frame OpenCV se
  `camera.wants_camera(prompt)` e non c'e' gia' un'immagine. Copre dashboard
  locale, telefono, `/watch/ask` e daemon (che usa lo stesso Engine). Dal
  telefono "cosa vedi" usa la webcam del PC, non quella del telefono.
  Gap noto, non fatto: la cattura schermo/Teams (`screen_context`) manca
  ancora in LiveBridge, c'e' solo in web_bridge e daemon.
- **Persona vocale** (`core/persona.py`): JARVIS dei film, del Lei,
  "Signore" raro, ironia asciutta occasionale e solo su fatti del contesto.
  Frasi fisse dei comandi rapidi senza ", Signore".

## Pannelli TradePilot e IVECO, recap daily, IVGAgent, ibrido VPS (2026-10-16, merge ce7303f)

- Dock: 📈 TradePilot (Dashboard/Dati/Esperimenti) e 🚛 IVECO (Recap daily,
  Job, IVGAgent), solo nella dashboard locale LiveBridge. Panoramica ora senza
  TradePilot/DevOps.
- Recap IVECO: `core/iveco.py`, lun-ven 09:30 da `bot.py::iveco_recap_loop`
  (controllo ogni minuto, salta se il PC si accende oltre 3 h dopo),
  `.iveco-recap.json` gitignored. Fonti: Databricks QAS/PRD, DevOps, Outlook.
  Teams non collegato.
- IVGAgent (cartella `Downloads/IVGAgent`, agente Claude Code Iveco): da JARVIS
  solo lettura via `core/ivg_dbx.py`. Scritture e avvio job restano ad
  Alessandro.
- Ibrido VPS pianificato, non ancora eseguito: guida
  `memory/playbooks/jarvis-vps.md`. Inoltro VPS -> PC non costruito.

## Ponte VPS attivo (2026-10-16, 15:25)

Telegram e Apple Watch passano dalla VPS TradePilot (`core/relay.py`, porta
9443 tailnet). PC acceso: gestisce tutto lui; PC spento: risponde la VPS con
meteo, TradePilot e second brain. Dettagli e aggiornamento in
`memory/playbooks/jarvis-vps.md`.

## Accesso dashboard via Tailscale senza password (2026-10-19, branch codex/tailscale-passwordless-dashboard)

LiveBridge accetta automaticamente l'identita' Tailscale Serve (`Tailscale-User-Login`)
per l'host `.ts.net` configurato. Tailscale Serve e' tailnet-only; Funnel non
inietta l'identita' e richiede la password. LiveBridge resta in ascolto su
loopback. Verificato dal PC via Serve: HTML 200 con marker, API senza login 200,
localhost senza cookie 401. L'iPhone deve ricaricare con Tailscale connesso.

## Collegamenti rapidi e microfono (2026-10-19)

Dashboard locale: dock Collegamenti apre Teams, Outlook Web e Databricks QAS
nel profilo browser persistente; il comando "collega le app" li apre tutti,
oppure si può indicare un servizio. SSO/MFA iniziale resta manuale nella
finestra browser; le sessioni successive vengono riusate.
Il mic dashboard parte spento. Il toggle comunica lo stato al daemon vocale;
con UI connessa e mic spento wake word e ascolto interruttivo sono disabilitati.

## Recap IVECO legge Teams (2026-10-21, branch feat/recap-teams)

Prima `core/iveco.py` scriveva `teams: non collegato` fisso: nessuna fonte
Teams esisteva, i Collegamenti aprivano solo il browser. Ora `_teams()` legge
la lista chat dal profilo Playwright gia' loggato (`BrowserAgent.read_teams_chats`):
titolo, tipo, ultimo messaggio, ora, non letta. Solo lista, mai chat aperte
(le segnerebbe come lette). Esclusa la chat con se' stesso (contiene credenziali).
Il recap gira in un thread: Playwright va chiamato sul loop del processo, quindi
`build_recap(loop=...)` da LiveBridge e bot.py. Verificato dal vivo: recap
dall'endpoint con `teams: ok`, 4 chat nella finestra, suite 520 test verde.
Se la sessione Teams scade: `teams: non disponibile (PermissionError)`, riaprire
Teams dai Collegamenti.

## Blocco bozze dietro proxy, recap 09:30 in LiveBridge (2026-10-21)

Il blocco "mai invio automatico" su Teams/Outlook non scattava: su questo PC gli
host passano dal proxy Defender for Cloud Apps (`*.mcas.ms`). Ora il suffisso
viene tolto prima del confronto. Il recap delle 09:30 gira in LiveBridge
(`iveco.recap_loop`), non piu' in bot.py, perche' solo LiveBridge tiene il
browser con Teams. Verifica: log `Recap IVECO programmato per ...` in `logs/live.log`.

## Recap daily con IVGAgent, pulsante DevOps (2026-10-23, 1636f92)
Il recap IVECO legge anche `Downloads/IVGAgent`: commit di ogni repo in `repo/` (tutti i branch, `--no-merges`, branch che contengono il commit), file non committati, file cambiati in `tools/knowledge/sql`. Esce come sezione "Sviluppi IVGAgent". Il pulsante Collegamenti DevOps apre `project_url` nel browser JARVIS; `azure_devops.connect()` avvia il login solo se serve.

## Chat condivisa Telegram ↔ dashboard (2026-10-23, 3e20d86)
`core/feed.py` scrive in `.jarvis-feed.jsonl` (ultime 300 righe, non versionato): `send_to_owner` (feed=True di default), messaggi in arrivo da Telegram, voce del daemon. Il LiveBridge (`broadcast_feed` in lifecycle) lo segue ogni 2 s e lo invia via websocket a tutte le console; `tasks_recent` lo unisce alla chat della sessione. Le risposte della chat dashboard vanno su Telegram con il prefisso 💻 e feed=False. Il mirror della dashboard Vercel (web_bridge) resta solo su Telegram.

## Evoluzione: audit e I0 costi (2026-10-27, branch feat/cost-guard)
Audit completo in sessione; piano incrementale I0-I8 (costi, memoria per ambiti, coordinatore a competenze, Life OS, decisioni, trading, finanza, emozioni, mentor). Decisioni di Alessandro:
- Il PC Iveco deve contenere solo applicazioni Iveco. Tutto il resto (memoria personale, finanza, emozioni, trading, Telegram) va spostato su VPS, Mac o archivio cifrato. La VPS attuale ha 1,6 GB: non regge JARVIS completo.
- Dashboard Vercel non usata: si usa solo il link Tailscale. Coda web spenta di default (`JARVIS_WEB_QUEUE=0`).
- Spesa LLM minima: `core/costs.py` registra ogni chiamata in `.costs.sqlite3`, tetti `JARVIS_DAILY_BUDGET_USD` (1,00) e `JARVIS_REQUEST_BUDGET_USD` (0,20); `/costi`. Alias haiku = `claude-haiku-5-5` (0,10/0,50 $/MTok) con effort low.
- Banche da collegare: Mediolanum (PSD2 via aggregatore, es. Enable Banking piano gratuito per conti propri), Wise (token personale UE senza saldi/estratti per PSD2), Zen (non verificato).
Stato: I0 su branch, testato su Mac, non ancora attivo sul PC ne' sulla VPS.

## Lentezza, piano B Outlook Web, schede Teams, sfera libera (2026-10-27, branch fix/outlook-web-teams-orb)
Diagnosi della lentezza, misurata dal vivo: rete via hotspot iPhone (ping 278 ms), Haiku 5.5 piu' lento di Haiku 4.5 al primo testo (circa 2 s contro 0,5-0,9 s), PC a batteria (STT CPU 5,4 s a frase), edge-tts instabile (1,3-6 s o voce Windows) e Outlook desktop appeso nel bot. Procedura: `memory/playbooks/diagnosi-lentezza.md`.
- Outlook: con una chiamata COM appesa le successive rinunciano entro 1 s (prima 45 s ciascuna). Piano B in sola lettura su Outlook Web (`core/outlook_web.py`): mail, conteggio, ricerca e agenda. Il browser e' di LiveBridge; bot.py e daemon passano da `POST /internal/outlook-web` con il token del Watch. Agenda in cache 10 min; accesso scaduto = 5 min senza nuovi tentativi. Aprire una mail dal piano B la segna come letta. Selettori OWA non verificati dal vivo: la sessione del profilo JARVIS era scaduta.
- Browser JARVIS: riusa la scheda Teams/Outlook gia' aperta (anche dopo il redirect su *.mcas.ms) invece di aprire un'altra istanza a ogni Collega/guarda Teams/recap; read/click/type seguono la scheda attiva. Causa strutturale ancora aperta: il Chromium di Playwright e' un browser non gestito, Conditional Access lo instrada via Defender for Cloud Apps e la sessione Microsoft scade. Candidato: Edge (`channel="msedge"`), da provare con Alessandro.
- Dashboard desktop: le finestre si spostano o si stringono per non coprire la sfera; se non c'e' spazio la sfera passa davanti (`orb-front`). Mobile invariato.
- Verifica dal vivo (2026-10-27 sera): piano B funzionante via LiveBridge. Base `https://outlook.cloud.microsoft.mcas.ms` (outlook.office.com va in ciclo di login nel Chromium JARVIS), scelta automatica dell'unico account gia' collegato (`core/browser.py::wait_ready`; la lettura chat Teams usa la stessa scelta account). Agenda solo per la settimana lavorativa corrente: OWA ignora la data nell'URL.
Stato: verificato dal vivo, servizi riavviati, merge su main. Attivo dopo il riavvio di LiveBridge, Bot e VoiceDaemon (la dashboard statica si aggiorna gia' al ricaricamento).

## Decisione dati sensibili (2026-10-27)
Alessandro approva la proposta B: dati sensibili (finanza, emozioni, trading personale) e chiave di cifratura sulla VPS, letti dal PC Iveco via Tailscale solo quando servono. Backup notturno cifrato dalla VPS a Google Drive personale. Il PC Iveco non conserva dati sensibili in chiaro. Da fare prima: limitare l'RDP della VPS a Tailscale (oggi aperto sulla porta 8328, richiede conferma separata).
(Recuperata dal branch `chore/merge-watch-timeout-2026-10-27`, mai arrivato su main.)

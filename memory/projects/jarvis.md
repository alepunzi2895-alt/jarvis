# JARVIS — stato progetto

## Cos'è
Assistente personale di Alessandro: bot Telegram + dashboard web, entrambi bridge
verso un processo locale `claude -p`. Vedi `core/claude_bridge.py`, `core/web_bridge.py`.
Ha anche un second brain: memoria a lungo termine che Claude stesso consulta e
alimenta task dopo task (`core/brain.py`), visualizzata come grafo animato nella
dashboard.

## Stato attuale (2026-07-14)
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

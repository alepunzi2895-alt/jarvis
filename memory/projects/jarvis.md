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
  tts.py edge-tts gratis), persona "Signore"/British/gentile solo su
  `channel="voice"`, `/voce on|off`. **Bug reale trovato e risolto**:
  Windows cambia il microfono di default quando colleghi una cuffia (Jabra,
  nel suo caso) — aggiunto `JARVIS_MIC_DEVICE` per pinnarlo per nome
  (`core/voice/__init__.py::resolve_input_device`).
- **(d)** `core/browser.py`: `BrowserAgent` (Playwright, profilo Chromium
  persistente `.browser_profile/`) — stesso pattern del second brain, Claude
  emette un blocco ` ```browser``` ` quando serve navigare un sito vero.
  Sicurezza a vocabolario limitato (solo open/search/screenshot, niente
  click/fill generico). Verificato con YouTube vera: cerca e apre il primo
  risultato corretto.

**Blocco (b) — EnvironmentRouter + MCPRouter**: unico ancora in pausa. Manca
il path per l'ambiente IVECO; da chiedere se vuole aggiungere altri MCP
server oltre TradingView (unico realmente configurato oggi).

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

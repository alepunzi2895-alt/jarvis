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

Piano approvato in Plan Mode a blocchi, con conferma tra uno e l'altro. Piano
architetturale generale in
`C:\Users\f45038c\.claude\plans\rosy-percolating-rivest.md` (viene riscritto
ad ogni nuovo blocco pianificato — non è più uno storico, solo il piano
corrente/più recente).

**Blocco (a) — fatto, mergiato in main**: `core/obsidian.py`
(`ObsidianVault`+`VaultWatcher`), `core/system_executor.py`
(`SystemExecutor` — sicurezza a **whitelist**, non blacklist, scelta esplicita
di Alessandro), comandi Telegram `/note /search /run /confirm /deny`.

**Blocco (c1) — fatto, branch `feature/jarvis-c1-floating-hud` (pushato, NON
mergiato — cambio visibile grosso, in attesa che Alessandro lo veda prima del
deploy)**: dashboard riscritta come HUD a finestre fluttuanti attorno a una
palla centrale animata (vedi log 2026-07-15 per il dettaglio). Pannello
camera con round-trip immagine→Claude, comandi vocali che aprono finestre,
second brain specchiato come note reali in Obsidian, `SystemExecutor.open_app`
esteso con risoluzione dinamica via registro Windows.

**Blocco (b) — EnvironmentRouter + MCPRouter**: in pausa, saltato apposta per
dare priorità a (c1)/(c2) su richiesta di Alessandro. Riprenderlo richiede: il
path per l'ambiente IVECO (ancora mancante), e se vuole aggiungere altri MCP
server oltre TradingView (unico realmente configurato oggi).

**Blocco (c2) — daemon vocale nativo**: non ancora pianificato in dettaglio
(wake word "ciao jarvis", STT/TTS, persona, apertura app *native* via voce —
quest'ultima impossibile dal browser per sandboxing, solo dal bridge locale).

**Vault Obsidian reale**: `C:\Users\f45038c\Downloads\jarvis\jarvis\` (creato
da Obsidian stesso dentro il repo del codice, non un path esterno — riconosciuto
dal `.obsidian/` interno). Escluso da git (`/jarvis/` in `.gitignore`).

**Ambienti locali sotto `C:\Users\f45038c\Downloads\`** (confermato da
Alessandro il 2026-07-14): `conciergebookings` = progetto **AURA**
(`WS_AURA` in `.env` ora punta lì); `ConciergeFlow` = progetto a sé, non
ancora un workspace nominato; `conciergebooking` (singolare) = da ignorare,
non è collegato a nessun progetto attivo — escluso dalla whitelist di
`SystemExecutor`. Whitelist attuale = repo JARVIS + `ConciergeFlow` +
`conciergebookings` + `property_scout`/`VMScout`/`tradeflow-ai`/`whitesoulibiza`.

**Decisioni architetturali chiave** (per orientare i blocchi successivi):
- Moduli Python diretti (Obsidian/SystemExecutor/futuro MCPRouter), non tutto
  instradato per forza da `claude -p` — necessario per la latenza del loop
  vocale nativo (blocco c2).
- MCP server realmente configurati oggi: solo **TradingView**. Google Drive/
  Calendar/Figma/Canva/Vercel non sono ancora collegati (serve Alessandro per
  OAuth/API key).
- L'ascolto vocale nella dashboard web (Web Speech API, wake word testuale
  "Jarvis") è un sistema diverso e separato dal futuro daemon vocale nativo
  del blocco (c2) (wake word audio reale, faster-whisper, ElevenLabs). Il
  browser NON potrà mai lanciare app native (Chrome, VS Code) — limite di
  sicurezza non aggirabile, solo il bridge locale può farlo.

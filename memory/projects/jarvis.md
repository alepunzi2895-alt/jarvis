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

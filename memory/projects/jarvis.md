# JARVIS — stato progetto

## Cos'è
Assistente personale di Alessandro: bot Telegram + dashboard web, entrambi bridge
verso un processo locale `claude -p`. Vedi `core/claude_bridge.py`, `core/web_bridge.py`.
Ha anche un second brain: memoria a lungo termine che Claude stesso consulta e
alimenta task dopo task (`core/brain.py`), visualizzata come grafo animato nella
dashboard.

## Stato attuale (2026-07-14)
Tre branch in sospeso, nessuno ancora mergiato in `main` (che resta al solo commit
iniziale):
- `fix/web-bridge-blocking` — fix del blocco long-poll Telegram; il poller web ora
  parla con Turso via HTTP pipeline diretta (`core/web_bridge.py`), non passa dal
  gateway Vercel (POST resettate su rete aziendale).
- `feature/hud-ui` — restyle dashboard in stile HUD "Iron Man/JARVIS" (quadrante
  circolare animato, readout, cornici ad angolo). File: `web/public/*`.
- `feature/second-brain` — creato da `fix/web-bridge-blocking` (serve il suo
  helper Turso) e poi mergiato con `feature/hud-ui` (per lo stesso stile sul
  pannello grafo). Aggiunge:
  - `core/turso.py` — client HTTP Turso condiviso (estratto da web_bridge.py).
  - `core/brain.py` — `fetch_context()`/`extract_and_store()`, tabelle
    `brain_nodes`/`brain_edges` (bootstrap automatico lato Python).
  - `core/claude_bridge.py` — inietta il contesto second-brain prima di ogni
    `claude -p` e processa il blocco ` ```brain ``` ` emesso da Claude dopo.
  - `web/api/jarvis.js` — azioni `brain_graph`/`brain_node_delete`.
  - Dashboard: pulsante 🧠 in header, pannello con grafo a forze su `<canvas>`
    (nodi colorati per workspace, enfasi su pill attiva o nodo cliccato).
  - Questo branch e' quello piu' avanti — contiene gia' dentro di se' sia il fix
    backend sia il restyle HUD (mergiati), oltre al second brain.

Deploy: Vercel project `jarvis-dashboard` (account `alepunzi2895-8998`). I preview
dei branch richiedono login Vercel (Deployment Protection) — normale, non un bug.
URL produzione: `jarvis-dashboard-green.vercel.app`.

## Prossimi passi noti
- Alessandro prova il pulsante 🧠 dal preview reale — il grafo parte vuoto finche'
  un task non genera almeno un nodo (serve un giro con `claude -p` vero, non solo
  il mock di verifica usato in sessione).
- Decidere ordine di merge verso `main`. Dato che `feature/second-brain` include
  gia' gli altri due, probabile che sia quello da mergiare (o da cui aprire la PR),
  gli altri due possono essere chiusi/superseded — da confermare con Alessandro,
  non farlo autonomamente (riscrive la storia dei branch pushati).
- Fase social (AURA + WhatsApp) resta bloccata da credenziali Meta che solo
  Alessandro puo' ottenere.

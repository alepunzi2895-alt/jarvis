# JARVIS — stato progetto

## Cos'è
Assistente personale di Alessandro: bot Telegram + dashboard web, entrambi bridge
verso un processo locale `claude -p`. Vedi `core/claude_bridge.py`, `core/web_bridge.py`.

## Stato attuale (2026-07-14)
- Backend: fix per il blocco del long-poll Telegram fatto su branch
  `fix/web-bridge-blocking` (pushato, non ancora mergiato in main).
- Frontend: restyle completo in stile HUD "Iron Man/JARVIS" (quadrante circolare
  animato, readout, cornici ad angolo) su branch `feature/hud-ui` (pushato da
  `main`, non ancora mergiato). File toccati: `web/public/index.html`,
  `web/public/style.css`, `web/public/app.js`.
- `main` locale/remoto è ancora al solo commit iniziale — entrambi i branch di
  lavoro partono da lì e non sono ancora stati uniti tra loro né in main.
- Deploy: Vercel project `jarvis-dashboard` (account `alepunzi2895-8998`). I
  preview dei branch richiedono login Vercel (Deployment Protection) — normale,
  non un bug. URL produzione: `jarvis-dashboard-green.vercel.app`.

## Prossimi passi noti
- Decidere ordine di merge dei due branch in main (bugfix backend e restyle UI
  sono indipendenti, nessun conflitto atteso: toccano file diversi).
- Richiesta in sospeso di Alessandro: un "second brain" — scope da chiarire prima
  di iniziare (non è chiaro se debba essere un nuovo modulo di JARVIS o un
  progetto separato).

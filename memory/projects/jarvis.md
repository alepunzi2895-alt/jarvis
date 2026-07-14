# JARVIS — stato progetto

## Cos'è
Assistente personale di Alessandro: bot Telegram + dashboard web, entrambi bridge
verso un processo locale `claude -p`. Vedi `core/claude_bridge.py`, `core/web_bridge.py`.
Ha anche un second brain: memoria a lungo termine che Claude stesso consulta e
alimenta task dopo task (`core/brain.py`), visualizzata come grafo animato nella
dashboard.

## Stato attuale (2026-07-14)
`main` è aggiornato (mergiato su richiesta esplicita di Alessandro, fast-forward
pulito): contiene fix del bridge web, restyle HUD e second brain insieme.
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
  pill attiva o nodo cliccato).
- I branch `fix/web-bridge-blocking`, `feature/hud-ui`, `feature/second-brain`
  restano su origin, ora superseded da `main` — non cancellati autonomamente,
  chiedere ad Alessandro se vuole ripulirli.

## Deploy — problema noto (Vercel Deployment Protection)
`jarvis-dashboard-green.vercel.app` (l'alias che Alessandro usa sempre) risponde
**404 NOT_FOUND diretto**, mentre gli URL generati da Vercel per la stessa
deployment (`jarvis-dashboard-<id>-...vercel.app`, `-git-main-...`) rispondono
`302` (redirect regolare al login SSO Vercel). Causa: l'alias "green" è stato
creato a mano via `vercel alias set` (sotto-dominio *.vercel.app), non è un vero
dominio custom nelle impostazioni del progetto — con la Deployment Protection
attiva, Vercel tratta questo tipo di alias diversamente e ritorna NOT_FOUND invece
del redirect SSO. Riprodotto 3 volte, non un blip. Non ho toccato le impostazioni
di Deployment Protection (security setting dell'account, decide lui). Stesso
pattern di alias usato anche per `tradeflow-ai`/`whitesoulibiza` — da controllare
se soffrono dello stesso problema.

## Prossimi passi noti
- Alessandro deve decidere su Vercel (Settings → Deployment Protection) se
  disattivarla per Production (probabile la vuole, dato che il dashboard deve
  essere raggiungibile dal telefono) o sistemare "green" come dominio vero.
- Nel frattempo: usare l'URL diretto del deploy (richiede un login Vercel).
- Il grafo second brain parte vuoto finché un task vero non ci scrive dentro
  qualcosa (il test di sessione ha usato dati finti, non scritti su Turso).
- Fase social (AURA + WhatsApp) resta bloccata da credenziali Meta che solo
  Alessandro può ottenere.

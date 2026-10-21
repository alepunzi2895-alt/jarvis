# JARVIS sulla VPS: ponte Telegram e Apple Watch

Attivo dal 2026-10-16. VPS = Windows Server 2022 di TradePilot
(`win-6gfp84o12pq.tail18e3c0.ts.net`, utente Administrator). Dal 2026-10-21
e' una macchina nuova (IP pubblico 154.61.184.38, RDP sulla 8328, porta 22
pubblica chiusa): SSH solo via Tailscale, alias `tradepilot-vps-ts`.
Stesso nome tailnet, quindi `JARVIS_TELEGRAM_RELAY_URL` sul PC non cambia.
Ponte reinstallato sulla macchina nuova il 2026-10-21 (task `\JARVIS\Relay`, 9443). Solo 1,6 GB di RAM, gia' in paging con MT5 e TradePilot:
sulla VPS gira SOLO `core/relay.py` (circa 40 MB), mai JARVIS completo.

## Come funziona
- La VPS legge Telegram (getUpdates) e serve `/watch/ask` su
  `https://win-6gfp84o12pq.tail18e3c0.ts.net:9443` (Tailscale Serve, solo tailnet;
  443 e 8443 restano di TradePilot).
- PC acceso: `bot.py` interroga `JARVIS_TELEGRAM_RELAY_URL/telegram/updates`
  (stesso formato di getUpdates, Bearer `JARVIS_RELAY_TOKEN`) e gestisce tutto
  come prima; risponde direttamente su Telegram. Le domande del Watch passano a
  `JARVIS_PC_WATCH_URL` (LiveBridge del PC).
- PC spento (nessuna interrogazione da 75 s) o messaggio non preso entro 6 s:
  risponde la VPS (Sonnet per Telegram, Haiku per il Watch) con meteo,
  TradePilot (loopback 127.0.0.1:8000), second brain Turso. Su Telegram le sue
  risposte iniziano con ☁️. Comandi `/` e note vocali solo a PC acceso.
- Meteo: posizione del Watch (lat/lon/city nel JSON) se arrivata nelle ultime
  12 ore, altrimenti quella del PC (.env o IP, inviata a ogni interrogazione),
  salvata in `C:\jarvis\.relay-location.json`.

## File sulla VPS
- `C:\jarvis` (clone da git bundle, ramo main), `.venv` con
  `requirements-relay.txt`, `.env` con solo Telegram, Anthropic, Turso, token
  ponte/Watch, URL PC (ACL: Administrator e SYSTEM).
- Task `\JARVIS\Relay`: all'avvio di Windows, S4U (non serve login), riavvio
  ogni minuto se cade. Log `C:\jarvis\logs\relay.log`.

## Aggiornare il ponte (dal PC)
1. `git bundle create <scratch>/jarvis.bundle main`
2. `scp jarvis.bundle install_relay.ps1 update_relay.ps1 tradepilot-vps-ts:C:/Windows/Temp/`
3. `ssh tradepilot-vps-ts 'powershell -NoProfile -ExecutionPolicy Bypass -File C:\Windows\Temp\update_relay.ps1'`
   (ferma il task, uccide il processo, pull dal bundle, pip, riavvia).
Gli script stanno nello scratchpad della sessione del 2026-10-21 (`scratchpad/vps`,
con `deploy_vps.ps1` che fa copia + installazione); se mancano, ricrearli da
questa descrizione. `env.vps` si rigenera dal `.env` del PC: Telegram,
Anthropic, Turso, `JARVIS_RELAY_TOKEN`, `JARVIS_WATCH_TOKEN` (= `.watch-token`
del PC), `JARVIS_PC_WATCH_URL` (= origin di `.live-config.json` + `/watch/ask`),
`JARVIS_IVECO_RECAP_TIME=off`. Il classificatore di Claude Code chiede un
permesso esplicito per scp/ssh in scrittura verso la VPS.

## Problemi gia' visti
- `ClientConnectorCertificateError` verso Telegram: lo store di Windows Server
  non ha tutte le radici; il ponte usa il bundle certifi.
- `RuntimeError` getUpdates = 409: un altro processo legge Telegram (bot.py del
  PC senza `JARVIS_TELEGRAM_RELAY_URL`).
- Bundle senza HEAD: clonare con `-b main`.

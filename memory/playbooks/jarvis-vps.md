# JARVIS sempre attivo sulla VPS (ibrido VPS + PC)

VPS = la Windows di TradePilot sulla tailnet (`win-6gfp84o12pq.tail18e3c0.ts.net`).
Gira gia' con task all'accesso dell'utente: JARVIS usa lo stesso schema.

## Chi fa cosa
- **VPS, sempre accesa**: Telegram (riceve i comandi), LiveBridge (dashboard da
  telefono, endpoint Watch), API Claude, second brain Turso, TradePilot in
  locale con curva equity continua.
- **PC**: voce e wake word, webcam, Outlook, Iveco (Databricks, IVGAgent,
  recap delle 09:30), controllo del PC. Continua a INVIARE su Telegram
  (promemoria, recap) ma non legge piu' i comandi.
- Mai sulla VPS: credenziali Databricks/Azure DevOps Iveco, `WS_IVECO`,
  IVGAgent. Il lavoro Iveco resta sul PC aziendale (percorso approvato IT).

## Passaggi
1. RDP sulla VPS. Controlla: Python 3.12 x64 (`py -3.12 --version`), Git,
   Tailscale collegato con MagicDNS. RAM libera ~1,5 GB (whisper small CPU).
2. Clona: `git clone https://github.com/alepunzi2895-alt/jarvis.git C:\jarvis`
   (repo privato: login GitHub o token una tantum).
3. `cd C:\jarvis`, poi `py -3.12 -m venv .venv` e
   `.venv\Scripts\python.exe -m pip install -r requirements.txt`.
4. Crea `C:\jarvis\.env` copiando DAL PC solo: `TELEGRAM_TOKEN`,
   `TELEGRAM_OWNER_ID`, `ANTHROPIC_API_KEY`, `TURSO_JARVIS_DB_URL`,
   `TURSO_JARVIS_AUTH_TOKEN`, `GITHUB_TOKEN`, `VERCEL_TOKEN`. Aggiungi:
   ```
   JARVIS_ALLOWED_DIRS=C:\jarvis
   JARVIS_CALENDAR_REMINDER_MINUTES=0
   JARVIS_IVECO_RECAP_TIME=off
   JARVIS_WEB_QUEUE=0
   JARVIS_DAILY_DIGEST_HOUR=-1
   JARVIS_LIVE_PASSWORD=<la stessa password della dashboard del PC>
   ```
   Copia il file via RDP (appunti/cartella condivisa), mai in chat.
5. `C:\jarvis\.tradepilot.json`:
   `{"origin": "http://127.0.0.1:8000", "dashboard_url": "https://tradepilot-ai-weld.vercel.app"}`
   (porta del backend TradePilot; se `TRADEPILOT_REMOTE=1` aggiungi
   `"remote_key"` con la stessa chiave del backend).
6. Dashboard: `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_live.ps1 -Start`
   -> `https://win-6gfp84o12pq.tail18e3c0.ts.net:8443` (Tailscale Serve, solo
   tailnet; la 443 di TradePilot non viene toccata).
7. Telegram, in quest'ordine (un solo lettore per bot, altrimenti 409):
   a. sul PC aggiungi `JARVIS_TELEGRAM_POLLING=0` al `.env` e riavvia il task
      `\JARVIS\Bot` del PC;
   b. sulla VPS: `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_autostart.ps1 -BotOnly`
      poi `Start-ScheduledTask -TaskPath '\JARVIS\' -TaskName Bot`.
8. Sempre attivo dopo un riavvio: accesso automatico di Windows sulla VPS
   (Sysinternals Autologon), come gia' serve a TradePilot/MT5. Chiudi RDP
   con la X (disconnetti), mai "Disconnetti utente".
9. Su Telegram invia `/voce off`: la VPS non ha casse, cosi' non prova a
   leggere le risposte ad alta voce.
10. Verifica: con il PC spento, `/help` su Telegram risponde; dal telefono la
   dashboard della VPS fa login e risponde; `logs\bot.log` e `logs\live.log`
   senza errori.
11. Watch: nel comando rapido URL della VPS + `C:\jarvis\.watch-token`.

## Aggiornare
`git pull` in `C:\jarvis`, poi Stop/Start-ScheduledTask di `Bot` e `LiveBridge`.

## Limiti noti
- Dalla VPS niente Outlook, Iveco, webcam, voce PC: JARVIS risponde che non ha
  la fonte. Inoltro VPS -> PC (quando il PC e' acceso) non costruito.
- "Apri Chrome" da Telegram agisce sulla VPS, non sul PC.
- Memoria conversazione SQLite separata per macchina; second brain condiviso.

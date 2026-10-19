# Voce privata iPhone-PC

1. Tailscale deve essere connesso su entrambi i dispositivi nella stessa rete.
   Verifica `tailscale status --json`; Running, Self.DNSName e URL dashboard
   sono piu' utili del link login temporaneo. Un 403 sul link di associazione
   non dimostra un guasto della dashboard.
   Dopo un riavvio Windows `tailscaled` puo' restare in `NoState` finche' non
   parte la GUI `C:\Program Files\Tailscale\tailscale-ipn.exe`: avviarla,
   attendere `BackendState` Running e controllare `tailscale serve status`.
2. `setup_live.ps1 -Start`: riserva HTTPS 8443 senza sovrascrivere un servizio
   diverso, proxy su loopback 8765, registra LiveBridge e AudioCleanup.
3. La dashboard accetta automaticamente l'identita' `Tailscale-User-Login`
   iniettata da Tailscale Serve sul dominio `.ts.net`. Serve deve restare
   tailnet-only: Funnel non passa l'identita' e richiede ancora la password.
   La password locale resta in `.live-password` per accessi non autenticati.
4. Verifica HTTPS 200, marker `JARVIS_LOCAL` e `JARVIS_TAILNET_AUTH`, cookie
   Secure/HttpOnly, WebSocket `/live/ws` con Origin uguale all'URL e `ready`.
5. Safari: tocca il mic per sbloccare sia registrazione sia playback; pronuncia
   Jarvis + comando. Stop ferma subito il suono, azioni OS gia' in esecuzione
   possono terminare prima del turno successivo. Cambio app interrompe il
   turno; al ritorno il mic mobile richiede un nuovo tap.
6. Nessun upload audio alla coda: in caso di disconnessione mostra errore e
   reinvio esplicito. Le risposte vocali usano edge-tts (testo inviato al
   servizio); lo STT e' locale. Telegram e dashboard Vercel restano separati.
7. Controlla `logs/live.log`, `Get-ScheduledTaskInfo` per AudioCleanup e il
   conteggio audio non NULL. Limite 5, tranne quelli pending/running protetti.
8. Dopo aggiornamenti server, non assumere che Stop-ScheduledTask uccida il
   figlio Python: controlla la porta e il PID. Su questo PC serve la chiusura
   manuale da parte dell'utente se resta vivo; non reiterare altri kill.
   Riavvia LiveBridge solo quando la porta e' libera.
9. Test: pytest servizio/claude_bridge/STT + Playwright Chromium e WebKit.
   Le prove reali di API e STT sintetico devono isolare history e logging
   second brain. Non promettere latenza iPhone da test su PC.

Su questa macchina, CUDA richiede prima driver NVIDIA/runtime compatibili.
Whisper espone il dispositivo effettivo nel ready, senza fingere GPU.

# Apple Watch — JARVIS via Comandi Rapidi

Dal 2026-10-16 il Watch chiama il ponte VPS, non il PC:
`POST https://win-6gfp84o12pq.tail18e3c0.ts.net:9443/watch/ask` (core/relay.py).
- PC acceso (bot.py interroga il ponte): la domanda passa al LiveBridge del PC,
  con Outlook, Iveco, memoria. PC spento: risponde la VPS (Claude Haiku,
  meteo, TradePilot, second brain).
- Header `Authorization: Bearer <token>`: lo stesso token del PC
  (`JARVIS_WATCH_TOKEN` o `.watch-token`), copiato anche nel `.env` della VPS.
- Corpo JSON `{"text": "...", "lat": .., "lon": .., "city": ".."}`. lat/lon/city
  facoltativi: aggiornano la posizione del meteo (vince sul PC per 12 ore) e
  vengono inoltrati al PC. Risposta `text/plain; charset=utf-8`.
- Timeout PC 55 s; se il PC non risponde in tempo il ponte restituisce 504.
  Rate limit 10 token sbagliati/min → 429.

Comando "Jarvis" (app Comandi su iPhone, "Mostra su Apple Watch" attivo):
1. Detta testo (italiano, "Interrompi ascolto: dopo una pausa").
2. Ottieni posizione attuale.
3. Ottieni dettagli di Posizione attuale → Città.
4. Ottieni contenuto dell'URL: URL sopra, Metodo POST, Intestazioni
   `Authorization` = `Bearer <token>`, Corpo JSON: `text` = Testo dettato,
   `lat` = Posizione attuale → Latitudine, `lon` = Posizione attuale →
   Longitudine, `city` = Città.
5. Pronuncia testo (Contenuti dell'URL), poi Mostra risultato.
Ultra: Impostazioni Watch → Tasto Azione → Comando rapido → Jarvis.
Permessi da concedere al primo avvio: microfono/dettatura, posizione,
"Consenti" verso il dominio ts.net.

Verifica dal PC (senza stampare il token): POST con token sbagliato → 401;
"che tempo fa" con lat/lon → 200 in ~3 s via PC, risposta dalla VPS a PC spento.

Aperto: il Watch senza SIM raggiunge il tailnet passando dall'iPhone? Non
documentato. Se dall'iPhone funziona e dal Watch no: Tailscale Funnel sulla
porta 10000 solo per `/watch/ask` (pubblico con token, da decidere con
Alessandro prima di attivarlo).

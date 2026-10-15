# Apple Watch — JARVIS via Comandi Rapidi

Endpoint: `POST <origine dashboard privata>/watch/ask` (core/live_server.py).
- Header `Authorization: Bearer <token>`. Token: `JARVIS_WATCH_TOKEN` in `.env`,
  altrimenti `.watch-token` (generato al primo avvio di LiveBridge, gitignored).
- Corpo JSON `{"text": "..."}`. Risposta `text/plain; charset=utf-8`.
- Stesso Engine/memoria della dashboard. Conversazione del Watch azzerata dopo
  15 min di silenzio. Timeout 55 s. Rate limit condiviso con il login (10
  errori/min → 429). Nessun controllo Origin solo su questo path.

Comando "Jarvis" (app Comandi su iPhone, "Mostra su Apple Watch" attivo):
1. Detta testo (italiano, stop dopo una pausa).
2. Ottieni contenuto dell'URL: POST, header Authorization, corpo JSON campo
   `text` = Testo dettato.
3. Mostra risultato (Siri lo legge se il comando parte con "Ehi Siri").
Ultra: Impostazioni → Tasto Azione → Comando rapido → Jarvis.

Verifica dal PC (senza stampare il token): POST con token sbagliato → 401,
con token giusto e "che ore sono" → 200 in ~0,3 s (intent, nessun costo API).

Aperto: il Watch raggiunge il tailnet passando dall'iPhone? Non documentato.
Se dall'iPhone funziona e dal Watch no, serve l'endpoint pubblico sulla VPS.

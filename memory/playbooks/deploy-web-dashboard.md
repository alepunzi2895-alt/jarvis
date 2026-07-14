# Playbook — Deploy dashboard/bot con bridge locale <-> Vercel

## Quando
Serve collegare un processo locale (bot, script) a una UI/API su Vercel senza aprire porte.

## Passi
1. Turso non ha CLI nativa Windows (solo macOS/Linux). Niente WSL solo per questo:
   usa direttamente l'API Platform di Turso via HTTP (`api.turso.tech`, token utente
   da app.turso.tech -> Account Settings -> API Tokens) per creare DB e token.
2. Verifica SEMPRE, prima di progettare il bridge, che le richieste POST verso il
   dominio target (`*.vercel.app`) funzionino davvero da questa rete/PC — non solo le GET.
   Su questo PC (rete via hotspot iPhone, nessuna VPN aziendale attiva) le POST verso
   `*.vercel.app` vengono resettate a livello di rete, mentre Turso e GitHub restano
   raggiungibili. Causa probabile: rate-limit/anti-abuse lato Vercel/Cloudflare scattato
   dopo troppi tentativi falliti ravvicinati durante i test — **non fare tentativi
   ripetuti a raffica con tool diversi (curl/node/python) sullo stesso endpoint**, anche
   un paio di retry con pausa bastano per capire se il problema è di rete o di rate-limit.
3. Se le POST verso Vercel non passano dal bridge locale: fai parlare il bridge
   DIRETTAMENTE con Turso (stessa HTTP pipeline API di `/v2/pipeline`) invece che
   passare dal gateway Vercel. Il browser (su rete diversa, es. telefono con dati
   mobili) continua a usare l'API Vercel normalmente.
4. Se un secondo task asyncio viene aggiunto a un loop che già esiste (es. bot Telegram
   con `requests.get(timeout=60)` in long-polling): quella chiamata è SINCRONA e
   monopolizza l'unico thread dell'event loop, affamando qualsiasi altro task asyncio
   che gira in parallelo. Avvolgere ogni chiamata `requests.*` bloccante in
   `asyncio.to_thread(...)` (per chiamate che servono il risultato) o
   `loop.run_in_executor(None, ...)` fire-and-forget (per notifiche tipo `send()`).
5. Vercel CLI (`npx vercel`) spesso è già autenticato su questo account
   (`alepunzi2895-8998`) — controlla con `npx vercel whoami` prima di chiedere login.
6. Git Credential Manager è già configurato (`credential.helper=manager`): il push
   HTTPS su GitHub apre il browser da solo, non serve un PAT manuale.
7. Verifica end-to-end SENZA passare da Vercel se il dubbio è di rete: inserisci una
   riga di test direttamente su Turso via HTTP, aspetta, rileggi lo status — isola se
   il problema è nel bridge o nella rete verso Vercel.

## Errori da evitare
- Non presumere che un dominio *.vercel.app sia raggiungibile in POST solo perché la
  home page risponde in GET.
- Non bombardare lo stesso endpoint con retry multipli da tool diversi per "testare" —
  rischia di far scattare un blocco anti-abuse che poi blocca anche l'utente reale.
- Non aggiungere un secondo task asyncio senza controllare che il primo non usi
  librerie sincrone bloccanti.

## Ultimo aggiornamento
2026-07-14

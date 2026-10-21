# Budget Vercel Fast Origin Transfer

Account Hobby di Alessandro: 10 GB di Fast Origin Transfer ogni 30 giorni,
condivisi da TUTTI i progetti (chat, tradeflow-ai, jarvis-dashboard, auraibiza,
vmscout, ...). Superato il limite Vercel puo' sospendere i progetti.

## Dove guardare
- Totale e per progetto: vercel.com/alepunzi2895-8998s-projects/~/usage, sezione
  Fast Origin Transfer, tab Projects (o `/~/usage/networking-fast-origin-transfer?view=Projects`).
- Il connettore Vercel MCP risponde 403 sul team: usare il Chrome di Alessandro.
- FOT molto piu' alto di Fast Data Transfer = traffico delle Functions, non asset statici.

## Cosa consuma FOT
Ogni byte in ingresso e in uscita da Function/Edge/Middleware: body delle POST
(upload), risposte delle API, poll frequenti (anche gli header contano, ~1 KB a chiamata).

## Regole per i progetti
- Mai poll che rimanda dati gia' noti: versione/ETag e risposta minima se invariato.
- Media e blob: scaricati una volta per id, mai dentro una lista ripetuta.
- Niente eco del body nella risposta di una POST.
- Poll lento o fermo con tab nascosta (`document.visibilityState`).
- Script/bot che sincronizzano (es. `tradeflow-ai/scripts/mt5-bot.py` -> `/api/db`):
  meglio scrivere direttamente su Turso che passare da una Function Vercel.

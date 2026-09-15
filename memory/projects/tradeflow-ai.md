# TradeFlow AI

## Cos'è
Agente autonomo di trading su XAU/USD.

## Architettura
- **Strategy Selector** — rileva il regime di mercato, sceglie la strategia.
- **Risk Guardian** — cinque livelli di rischio, circuit breaker.
- Strategie: MFKK Intraday, MFKK Scalping, OB+FVG Scalp, Elite Golden Squeeze, Convergence Scalp.

## Dati
Export JSON da MT5. Log self-learning in `07_self_learning_log.md`.

## Regole ferree
- Jarvis NON esegue ordini reali. Mai.
- Solo: analisi, backtest, report giornaliero, sanity check del codice.

## Stato (aggiornato 2026-09-15, sola lettura — JARVIS non tocca quel repo)

**Il bug del 2026-07-16 qui sotto risulta risolto nel codice**, in due
tempi: fix di `_strategy_order_tickets` (deadlock `count_open_positions`)
deployato il **2026-09-02** con riconciliazione attiva a due-strike nel
sync loop, poi un secondo bug del circuit breaker (si armava e restava
latchato — tre difetti additivi in `risk_guardian.py`/`mt5-bot.py`/
`risk_manager.py`) risolto il **2026-09-09**. Entrambi i fix in
`directives/06_known_issues.md` **richiedono un riavvio del bot sulla
VPS** per svuotare lo stato in-memory — **non verificato da qui se quel
riavvio sia stato fatto davvero** (JARVIS non ha accesso alla VPS, solo al
repo locale): da chiedere direttamente ad Alessandro.

Sviluppo locale molto attivo da allora fino a ieri (2026-09-14): nuove
card dashboard "stile MFKK", fix indicatori (Alligator SMMA invece di EMA,
Ultimate RSI), un test che ha confermato che il confidence score S32/S33/
S34 NON predice l'esito delle entry (ipotesi scartata, non un bug).

**🟡 Cron giornaliero ancora fermo — probabilmente da prima di luglio,
mai ripreso.** `daily_maintenance.log` ha voci reali solo fino al
2026-07-09, poi un salto diretto a poche righe di backtest manuale del
2026-09-01 (nessuna esecuzione automatica di schedule in mezzo);
`daily_report_2026-07-09.txt` resta l'**unico** report mai generato — lo
stesso problema segnalato il 2026-07-16, mai risolto in 2 mesi. Sembra
scollegato dal lavoro di sviluppo (che è manuale/locale, non passa dal
cron) — probabilmente lo scheduled task sulla VPS non gira più o non è
mai stato ripristinato.

**Backlog aperto, ancora tracciato in `directives/06_known_issues.md`**
(bassa priorità, non toccato): `memCache` senza cleanup in
`api/webhook.js`, `TV_WEBHOOK_SECRET` non attivato, `onclick` binding
silenziosi in `public/app.js`, timeout esplicito mancante in `api/db.js`.

**Prossimo passo**: chiedere ad Alessandro (a) se ha già riavviato il bot
sulla VPS dopo i fix del 09-02/09-09, (b) se il cron giornaliero
(`daily_maintenance.py`) sia ancora schedulato da qualche parte o vada
ricreato da zero.

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

## Contesto business e trading (dal profilo operativo di Alessandro, 2026-09-15)
Trader algoritmico focalizzato su **oro (XAU/USD)** via MT5, track record
verificato su Myfxbook (account MFKK). Obiettivo di fondo: passare da
trading manuale/segnali a sistemi davvero data-driven.

**GoldKilla EA v4.0** (MQL5, separato da TradeFlow ma stesso dominio):
lotto con compounding, doppio TP (chiude 50% a 1R, trailing del resto
verso 2R+), confluenza doppia EMA su H1+H4, ADX ≥ 22, filtro zone RSI,
circuit breaker settimanale a -3%.

**Pipeline Telegram → MT5** (Node.js/Express + Telegraf + lo stesso EA
MQL5): funziona ma **non è pronta per produzione** — manca parsing
robusto dei segnali, ridondanza, logging, kill switch su drawdown.
Prossimo passo dichiarato: irrobustire parser + controlli di rischio +
test su demo prima di qualunque uso reale.

**Sistema di ricerca strategie** (concept, Python separato da TradeFlow):
stack previsto VectorBT/Backtrader/NautilusTrader, dati Dukascopy/
Binance/Polygon, note in Obsidian + Dataview. Domande ancora aperte:
disponibilità di dati storici di qualità, capitale e scopo operativo
reale.

**Indicatore TradingView proprietario**: riproduzione Pine v5 di un
indicatore privato XAU/USD M5 — Bollinger 45/1.8, EMA ribbon 20/50, MA
9/21, EMA lenta 100, Fibonacci lookback 50, segnali sugli estremi
locali.

**Filosofia di validazione** (la lezione più importante per chiunque
lavori qui): i cicli automatici genera-strategia → testa → promuovi sono
**data mining bias**, non un vero edge. Il valore sta nella
**validazione**: walk-forward, Deflated Sharpe Ratio, Monte Carlo,
out-of-sample vero (metodo López de Prado) — non nel generare sempre
nuove varianti.

**Lezioni tecniche minori**: CSS sempre inline (`<style>`, non
`<link>`) per evitare FOUC che rompe il layout su Vercel; TradingView
Scanner bloccato da CORS + IP AWS di Vercel, fonte prezzi affidabile
resta Yahoo Finance (`XAUUSD=X`/`XAGUSD=X`); Telegram → MT5 va sempre
mediato da un backend, mai diretto; nei refactor tenere un file baseline
funzionante per confronto.

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

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

## Stato (controllato 2026-07-16, sola analisi — JARVIS non tocca quel repo)

**🔴 Bot fermo dal 2026-07-10.** Bug reale in `scripts/mt5-bot.py`
(`_strategy_order_tickets`): alla chiusura di una posizione, `strategy_closed`
viene derivato dal commento MT5 troncato dal broker (es. `S18_RANGE_` invece
di `S18_RANGE_REVERSAL`) e usato per fare il `pop()` dell'entry in memoria —
la chiave troncata non combacia mai con quella piena, il pop fallisce in
silenzio, l'entry resta agganciata per sempre. Risultato: `count_open_positions()`
resta bloccato a 2 anche con **0 posizioni reali** (confermato in diretta via
`/api/db mt5_get`: `positions: []` ma `bot_status.open_positions: 2`) →
deadlock su tutti i blocchi segnale (H1/M15/M30/H4) → **zero nuovi ordini su
tutte le strategie da 6 giorni**. Fix identificato e documentato in
`directives/06_known_issues.md` ma **non ancora deployato**; serve comunque un
riavvio del bot sulla VPS per svuotare lo stato in-memory anche dopo il deploy
del fix.

**🟡 Cron giornaliero fermo da una settimana.** `daily_maintenance.log` si
ferma al 2026-07-09 11:42 (ultimo `daily_report_2026-07-09.txt`); nessun log/
report più recente nonostante oggi sia il 2026-07-16 — da controllare se lo
scheduled task sulla VPS è ancora attivo. (`daily_update.py`, script più
vecchio, ha il suo log fermo al 2026-05-15: sembra superseduto da
`daily_maintenance.py`, probabilmente non un problema a sé.)

**Backlog aperto, già tracciato in `directives/06_known_issues.md`** (bassa
priorità, non toccato): `memCache` senza cleanup in `api/webhook.js`,
`TV_WEBHOOK_SECRET` non attivato, `onclick` binding silenziosi in
`public/app.js`, timeout esplicito mancante in `api/db.js`.

Nessun'altra anomalia nella storia recente dei commit (`git log`): fix e
retirement di strategie deboli (S05), rivalidazione SL adattivo S16,
aggiornamento model ID Anthropic deprecato — attività normale, ben
documentata nel proprio `07_self_learning_log.md`.

**Prossimo passo**: Alessandro (o una sessione Claude Code dedicata dentro
`tradeflow-ai`, non JARVIS — regola ferrea sopra) deve deployare il fix di
`_strategy_order_tickets` e riavviare il bot sulla VPS, poi verificare se il
cron giornaliero è ancora schedulato.

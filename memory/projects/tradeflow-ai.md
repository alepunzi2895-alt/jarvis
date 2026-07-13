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

## Stato
<aggiornare>

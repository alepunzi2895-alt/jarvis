# TradePilot — integrazione JARVIS

## 2026-10-13
- Repository locale distinto da TradeFlow AI, scoperto dal catalogo dinamico. Alias conversazionali TradePilot / trade pilot.
- Collegamento privato VPS Tailscale da JARVIS configurato, solo GET. Nessuna modifica al repository TradePilot o al funzionamento del trading.
- Conto osservato: demo. API con snapshot equity/saldo/drawdown; JARVIS raccoglie un punto reale/minuto su SQLite separando i conti. Storico precedente al collegamento non disponibile.
- Ricerche: 24 esperimenti e 8 righe statistiche strategia/modalita osservate. Registry VPS con 22.644 tentativi e 0 eligible; STATE sul PC citava 26.644. Non sostituire dati VPS con note locali o dire che il lavoro locale e gia rilasciato.
- Sono dati datati: usare get_tradepilot per stato attuale e specificare demo/shadow/counterfactual, numero operazioni e fonte. Niente ordini reali o promozioni automatiche.
- Dashboard JARVIS: Panoramica -> Equity e deploy, dettagli Ricerche e strategie; una sola conversazione. Attivazione backend dopo riavvio LiveBridge.
- Procedura: `memory/playbooks/connected-memory-and-data.md`.

Attivazione JARVIS completata alle 18:05 Europe/Rome: API private e grafico
equity verificati sul servizio Windows e in WebKit mobile. Il registro VPS
espone ora 25 esperimenti, 8 righe statistiche, conto demo; dati aggiornati
rispetto alla prima verifica. Raccolta campioni attiva in LiveBridge.

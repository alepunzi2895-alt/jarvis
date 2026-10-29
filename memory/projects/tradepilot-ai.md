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

## Prossimi step e consigli (JARVIS, aggiornato 2026-10-29)
Dalle conversazioni con JARVIS. Il conto demo è operativo: equity circa 3.060 euro, drawdown dello 0,9%, settimana a +1,6%. La ricerca conta quasi 48.000 prove senza strategie idonee; 8 strategie sono in ricerca e 17 in shadow.

Prossimi step:
- Verificare la modifica non committata sul ramo exp062-bce01 dell'integrazione JARVIS, dopo l'allineamento con origin/main.
- Proseguire la ricerca sulle 8 strategie in fase di ricerca finché una non raggiunge i numeri per la produzione.
- Monitorare lo shadow trading delle 17 strategie.

Consigli:
- Equity, drawdown e variazioni sono letture della VPS di oggi alle 16:45: aggiornarli prima di usarli per decisioni.
- Le prove di ricerca non sono rendimento del conto: tenerle separate dai risultati reali.
- Le strategie in shadow trading non sono operative: non considerarne i risultati come guadagni reali.
- Suggerimento JARVIS: fissare criteri quantitativi espliciti (rendimento, drawdown, numero minimo di trade) per decidere quando una strategia passa in produzione.

# Pull progetti

Aggiornato 2026-10-29.

## Comando unico (Windows e Mac)
Da `jarvis/`:
```
bash tools/pull_progetti.sh              # tutti i progetti elencati
bash tools/pull_progetti.sh aura conciergeflow   # solo quelli indicati
```
Percorsi sempre `~/Downloads/<cartella>`: su Windows (Git Bash) `~` = `C:\Users\f45038c`, su Mac = `/Users/<utente>`. Regole: solo `pull --ff-only origin main`; salta repo assenti, ramo diverso da main, modifiche non committate.

## Stato 2026-10-29
- aura (`auraibiza`): pullato a `8e5d600`.
- conciergeflow: pullato a `1ab4214`. Nota: indice con voce staged `AM ConciergeFlow` (gitlink annidato, 1 riga). Non toccata: va verificata da te (`git -C ~/Downloads/ConciergeFlow status`).
- whitesoul: pullato a `7257698`.
- vmscout, trading (tradeflow-ai), eyra, alessandropunzi-systems: pullati dallo script con `ff-only` (non richiesti esplicitamente, segnalati qui).
- property-scout: 10 file modificati, pull saltato.
- tradepilot-ai: ramo `exp062-bce01`, pull saltato.
- ivgagent: cartella assente su questa macchina.

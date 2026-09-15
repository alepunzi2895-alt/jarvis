# Property Scout

## Cos'è
`C:\Users\f45038c\Downloads\property_scout`. Sistema di discovery fornitori
turistici (ville, barche, auto...) per il business di concierge di lusso —
strumento di supporto per AURA Ibiza, non un prodotto a sé rivolto a terzi.

## Come funziona
8 canali reali di scraping/ricerca: Google Maps (via Serper.dev), Instagram
e Facebook Pages (via Apify), Telegram pubblici (fetch diretto t.me/s/),
MediaVacanze/Subito.it/Idealista (scraping HTML), Immobiliare.it (Apify).
NLP + scoring AI (Anthropic) + generazione messaggi di primo contatto per i
fornitori trovati. Categoria barche/auto con ordinamento per prezzo più
basso (ultimo commit).

## Stack
Vercel Serverless (`api/`) + frontend statico. Env: `ANTHROPIC_API_KEY`,
`SERPER_API_KEY`. Costo dichiarato nel README: ~0 EUR/mese in uso normale.

## Stato (controllato 2026-09-15, sola lettura)
Ultimo commit 2026-06-04. Nessun CLAUDE.md — solo README, meno documentato
degli altri progetti di Alessandro. Un file non tracciato in git
(`package-lock.json`, mai committato) da inizio progetto.

**Nota sul deploy**: il README istruisce a fare `git push origin main
--force` per pubblicare — pattern rischioso (sovrascrive la storia remota
senza controllo) rispetto agli altri repo, da non replicare altrove senza
che sia lui a chiederlo esplicitamente.

## Collegamento con JARVIS
In `JARVIS_ALLOWED_DIRS` (sola lettura), non in `WORKSPACES` né in
`project_status.PROJECTS` — stesso trattamento di VMScout: JARVIS può
leggerlo su richiesta esplicita, ma `/progetti` non lo controlla.

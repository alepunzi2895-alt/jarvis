# White Soul Ibiza

## Cos'è
`C:\Users\f45038c\Downloads\whitesoulibiza` (`WS_WHITESOUL` in `.env`). Sito
statico multi-pagina per un servizio di concierge/eventi di lusso a Ibiza —
brand diverso da AURA, stesso settore. Target clientela alto-spendente,
5 lingue (EN/IT/ES/FR/DE).

## Stack
HTML5 statico, no framework/build step. `styles.css` unico, `script.js`
unico (header, carousel, cambio lingua, fetch Turso). Font Cormorant
Garamond (display) + Inter (body). Traduzioni in Turso (libsql), non nei
file statici. Icone SVG inline, immagini placeholder Unsplash (da
sostituire con foto vere).

Ordine di navigazione fisso e documentato in CLAUDE.md: Home → Services →
Experiences → About → Contact (Events dentro services.html#events,
Testimonials dentro about.html — rimossi dalla nav esplicita).

## Stato (controllato 2026-09-15, sola lettura)
Ultimo commit 2026-06-28 ("Update about page hero: warmer Ibiza scene").
Nessuna anomalia trovata nello storico recente.

## Collegamento con JARVIS
Già uno dei 3 progetti monitorati da `/progetti` e dal digest mattutino
(`core/project_status.py`, insieme ad Aura e TradeFlow) — l'unico dei
progetti "minori" con questo trattamento, perché già configurato in
`WORKSPACES` (`WS_WHITESOUL`).

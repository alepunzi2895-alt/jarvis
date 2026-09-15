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

## Brand e strategia (dal profilo operativo di Alessandro, 2026-09-15)
Proprietà gestite: **Villa Vivian**, **Boutique Boat Can Vedra**. Logo
monogramma "WSI" in SVG.

Quattro pilastri: esclusività ("not for everyone"), servizio senza
sforzo (un solo referente per il cliente), esperienza (la villa è
l'ingresso all'esperienza, non il prodotto in sé), Ibiza autentica (non
da cartolina). Target: clientela internazionale facoltosa — lingua
primaria inglese, poi IT/ES.

Strategia di conversione: **"public desire, private access"** —
desiderio costruito su Instagram, conversione vera su WhatsApp. Follower
= metrica di vanità, non l'obiettivo: contano qualità delle
conversazioni, salvataggi, condivisioni.

Font (di brand, distinti dal solo stack tecnico sopra): Italiana,
Cormorant Garamond, Inter.

**Fatto finora**: sito single-file 8 pagine (EN/IT/ES/FR), 13 Stories
Canva in spagnolo (stile bianco minimale), link WhatsApp con
attribuzione per PR, messaggio di benvenuto trilingue ("su misura /
tailored / a medida").

**Da fare**: scegliere il copy dell'hero definitivo, piano editoriale a
30 giorni, fix dell'encoding dei link PR (`%20` vs `+` negli URL).

## Collegamento con JARVIS
Già uno dei 3 progetti monitorati da `/progetti` e dal digest mattutino
(`core/project_status.py`, insieme ad Aura e TradeFlow) — l'unico dei
progetti "minori" con questo trattamento, perché già configurato in
`WORKSPACES` (`WS_WHITESOUL`).

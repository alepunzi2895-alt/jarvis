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

## Stato (aggiornato 2026-10-29, sola lettura)
Pull eseguito 2026-10-29: clone allineato a `origin/main` 7257698. Storico: clone era fermo a 4113cc8 (giugno 2026), `origin/main` avanti di 30+ commit
(7257698, autore `ZeroDay` = Alessandro dal suo Mac, confermato 2026-10-29, ultimi 3 giorni: foto ville, pagina yachts, account/progetti
salvati, traduzioni, `lib/server.js`, `api/google.js`, `api/translations.js`). Il clone
non ha questi cambi: `/progetti` mostra solo "Origine avanti: 7257698", senza elenco.
**Rischio aperto**: il token Turso read-write era hardcoded in `seed-db.js`; rimosso in
e42f5af ma ancora nella storia git (es. e217add, cb13567). Va ruotato, non basta il fix.

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

## Prossimi step e consigli (JARVIS, aggiornato 2026-10-28)
Dalle conversazioni con JARVIS. Sito statico HTML per White Soul Ibiza da portare su hosting Aruba, con in più un pacchetto di manutenzione del sito e gestione Instagram a canone mensile; obiettivo chiusura entro fine mese.

Prossimi step:
- Sistemare il token Turso, che nel client è read-write e visibile a chiunque, prima del passaggio ad altro gestore.
- Sostituire le immagini Unsplash con foto reali.
- Aggiornare il numero WhatsApp placeholder.
- Verificare che il cliente abbia gli accessi Instagram.
- Migrare il dominio su Aruba e configurare l'hosting.
- Definire lo scope del pacchetto Instagram: numero di post al mese, calendario approvato dal cliente, nessuna pubblicazione senza suo ok esplicito.

Consigli:
- Tenere separate le due offerte: manutenzione del sito come canone fisso, gestione Instagram come pacchetto a parte, così lo stop di una non trascina l'altra.
- Indicativamente: setup e configurazione del dominio una tantum tra 300 e 800 euro, hosting come piccolo ricarico sul costo reale, manutenzione mensile tra 150 e 350 euro, da confrontare con il mercato locale.
- Lo stack è HTML statico senza build, quindi Aruba basta e costa poco.

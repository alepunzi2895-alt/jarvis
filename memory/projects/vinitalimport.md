# Vinitalimport

## Cos'è
Catalogo PDF vini per un importatore a Ibiza-Formentera — progetto
separato da AURA (settore diverso, cliente diverso).

## Contenuto
161 vini (DO italiane e spagnole). Mappe GeoJSON regionali con punti
rossi per zona di provenienza. Font: Cinzel, Cormorant, EB Garamond.

Due versioni prodotte: con prezzi e senza prezzi, più un Excel con i
link alle immagini.

## Stack
WeasyPrint per la generazione PDF (stesso strumento usato per i listini
AURA) — coerente con la preferenza generale "WeasyPrint/Playwright per
generazione, PyMuPDF per editing" già nota.

## Collegamento con JARVIS
Workspace "vino" esiste già nel dizionario `WORKSPACES` di
`core/claude_bridge.py` ma senza `WS_VINO` configurato in `.env` (cade
sul path di JARVIS_HOME di default) — da collegare quando avrà un repo/
cartella locale reale. Non in `JARVIS_ALLOWED_DIRS`.

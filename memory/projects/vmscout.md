# VMScout (Visual Marketing Scout)

## Cos'è
`C:\Users\f45038c\Downloads\VMScout`. Tool "anti-stock, anti-AI, solo
autenticità" per marketer: genera strategie visive, storyboard video, piani
editoriali (soprattutto IG/FB) e suggerimenti di post cross-platform. Tema
scuro (`#0D0D0D`/`#080808`, accenti gold `#C9A96E`).

## Stack
Vite + React (vanilla CSS, no Tailwind) + Vercel Serverless Functions
(`api/`) + Turso (libsql) + Anthropic Claude (`api/chat.js`, server-side,
supporta anche immagini). Foto/video da Pexels + Pixabay. Canva Connect API
v1 (OAuth2 PKCE) per generare design/caroselli. Instagram/Meta Ads via
token incollato a mano (non piu' OAuth "Connetti Facebook", cambiato il
2026-09-09).

Direttive complete e sempre aggiornate in `PROJECT_DIRECTIVES.md` — è il
CLAUDE.md di questo progetto, solo con un nome diverso.

## Stato (controllato 2026-09-15, sola lettura)
Progetto maturo e molto attivo: ultimo commit 2026-09-09 ("elimina design →
Cestino Canva"). Diventato **multi-utente** lo stesso giorno — prima era
mono-utente (solo Alessandro): login nickname+password, isolamento
per-utente completo (progetti, localStorage namespacizzato, credenziali
OAuth Meta/Canva per-utente con fallback alle env Vercel per lui). UI ora
in 5 lingue (IT/EN/ES/FR/DE), con una coda di stringhe non ancora tradotte
tracciata direttamente in `PROJECT_DIRECTIVES.md` §1.

Ogni progetto/brand gestito ha una "memoria" che si auto-aggiorna
(`project_insights.directives`, riscritta dall'AI dopo ogni analisi — vedi
`docs/PROJECT_LEARNING_LOOP.md`), stesso principio del second brain di
JARVIS ma scoped per singolo progetto invece che globale.

## Collegamento con JARVIS
`C:\Users\f45038c\Downloads\VMScout` **è** in `JARVIS_ALLOWED_DIRS` (whitelist
sola-lettura di `SystemExecutor.git()`), ma **non** in `WORKSPACES`
(`core/claude_bridge.py`) né in `project_status.PROJECTS` — quindi `/apri`/
`/run`/i controlli git diretti funzionano se richiesti esplicitamente, ma
`/progetti` e il digest mattutino non lo controllano mai. Nessun WS_VMSCOUT
in `.env`.

## Non ancora verificato/da approfondire
Se sia effettivamente in uso attivo da altri utenti oltre Alessandro (il
multi-utente è recentissimo, 2026-09-09) o sia ancora preparazione per un
lancio.

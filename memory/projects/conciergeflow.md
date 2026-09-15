# ConciergeFlow

## Cos'è
Gestionale per concierge/property manager, affitti brevi e lunghi — SPA
multi-lingua (IT/EN/ES) e multi-tenant, Vanilla JS ES6, nessun framework.
Design "Nocturnal Clarity v3.1" (dark, gold `#d4a24a`, font Outfit).
Moduli: dashboard, prenotazioni, contabilità, gestione proprietà/partner,
analisi. Turso (libSQL) come DB distribuito, niente backend server-side
proprio (file statici + client Turso via CDN).

## ATTENZIONE — anomalia di repository trovata il 2026-09-15
`C:\Users\f45038c\Downloads\ConciergeFlow` contiene un **repo Git annidato
dentro se stesso**: `C:\Users\f45038c\Downloads\ConciergeFlow\ConciergeFlow`
ha una propria cartella `.git`, stesso remote
(`github.com/alepunzi2895-alt/ConciergeFlow.git`) del repo esterno.

- **Esterno** (`ConciergeFlow/`): HEAD fermo a `e4c05c5` (2026-04-08) — un
  clone vecchio, mai più toccato dopo aprile. `git status` lo segna
  "dirty" (`AM ConciergeFlow`) perché Git tratta la cartella annidata come
  un gitlink (voce stile submodule), non perché manchi qualcosa di reale.
- **Interno** (`ConciergeFlow/ConciergeFlow/`): HEAD a `1ab4214`
  (2026-06-05) — **verificato allineato 1:1 con `origin/main`**, quindi
  nessun lavoro a rischio di perdita. Contiene molto più dell'esterno
  (CLAUDE.md, ROADMAP.md, admin_cleanup.html, analisi.html, pulizie.html):
  è il vero checkout attivo, probabilmente nato da un `git clone` fatto per
  sbaglio dentro la cartella esistente invece che altrove.

**Non toccato**: è un problema di igiene del filesystem locale di
Alessandro, non una perdita di dati — a lui la scelta se ripulire (es.
cancellare l'esterno stale e spostare l'interno al suo posto) o lasciarlo
così. `JARVIS_ALLOWED_DIRS` punta all'esterno (`.env`:
`C:\Users\f45038c\Downloads\ConciergeFlow`) — se in futuro JARVIS legge lo
stato git di questo path, sta leggendo il clone SBAGLIATO/vecchio (aprile),
non quello vero (giugno, allineato a origin/main).

## Stato (controllato 2026-09-15, sola lettura)
Ultimo lavoro reale (repo interno): 2026-06-05, "refactor: contabilità —
costi fissi e variabili separati + categorie sensate". Attivo fino a
inizio giugno, nessun commit più recente trovato.

## Collegamento con JARVIS
In `JARVIS_ALLOWED_DIRS` (sola lettura, path esterno/stale — vedi sopra),
non in `WORKSPACES` né in `project_status.PROJECTS`.

# JARVIS — fase 1
stopp
Telegram -> Claude Code sul tuo PC. Nessun tunnel, nessuna porta aperta.

## Setup (10 min)

**1. Crea il bot**
Telegram -> `@BotFather` -> `/newbot` -> copia il token.
Telegram -> `@userinfobot` -> copia il tuo user id.

**2. Configura**
```
copy .env.example .env      (Windows)
cp .env.example .env        (Mac/Linux)
```
Compila `TELEGRAM_TOKEN`, `TELEGRAM_OWNER_ID`, i path `WS_*`.

Windows: `CLAUDE_BIN` di solito è
`C:\Users\<TU>\AppData\Roaming\npm\claude.cmd`
(verifica con `where claude`)

**3. Avvia**
```
start.bat        (Windows)
./start.sh       (Mac/Linux)
```

## Uso

| Comando | Cosa fa |
|---|---|
| `/ws aura` | passa al workspace AURA |
| `/new` | azzera la sessione |
| `/status` | workspace + sessione attiva |
| `/log` | log di oggi |
| testo libero | task da eseguire |

Esempi:
- `/ws aura` poi `Genera 5 caption IG per Cala Tarida, EN/ES/IT`
- `/ws trading` poi `Leggi ultimo export MT5, dammi report della settimana`
- `/ws vino` poi `Rigenera il catalogo con i prezzi aggiornati`

## Sempre acceso
- Windows: Utilità di pianificazione -> attività all'accesso -> `start.bat`
- Mac: `launchd` plist, oppure `pm2 start start.sh`

## Dashboard su iPhone

- Apri la dashboard in Safari; puoi aggiungerla alla schermata Home.
- Un pannello alla volta, controlli touch da 44 px e layout che segue la
  tastiera e le aree sicure dello schermo. La barra comandi scorre lateralmente.
- Tocca il microfono, autorizzalo e pronuncia «Jarvis» seguito dal comando.
  Su mobile l'ascolto si ferma cambiando app o interrompendo l'audio: per
  riprenderlo torna alla pagina e tocca il microfono. Non è un wake word di sistema.
- La trascrizione resta sul PC. Il trasporto attuale passa ancora da
  Vercel/Turso e la voce di risposta esce dal PC: il collegamento privato
  diretto e la riproduzione sul telefono non sono ancora implementati.

Per ridurre la latenza completa servono una GPU con runtime compatibile,
trascrittore già caricato, connessione persistente al PC e risposta generata
e riprodotta per frasi. Le operazioni lunghe devono mostrare un avanzamento
senza essere dichiarate concluse prima dell'esito. Misurare il tempo dalla
fine del parlato al primo audio reale; un'animazione non vale come risposta.

Test del browser con API e microfono simulati, senza accesso al DB reale:

```powershell
.venv/Scripts/python.exe -m playwright install chromium webkit
.venv/Scripts/python.exe -m pytest -q tests/test_dashboard_mobile.py
```

L'emulazione WebKit non sostituisce la prova di permessi, microfono e tastiera
su un iPhone fisico.

## Come impara
Ogni task scrive in `memory/log/`. Le procedure riuscite finiscono in
`memory/playbooks/`. La sessione dopo li rilegge (regola in `CLAUDE.md`).
Memoria = git. `git commit` la memoria ogni settimana.

## Fase 2
- Cron notturno: report trading + bozze contenuti al risveglio.
- Bottoni Approva/Rifiuta su Telegram per le azioni sensibili.
- UI Vercel se serve più della chat.

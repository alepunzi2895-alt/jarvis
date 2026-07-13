# JARVIS — fase 1

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

## Come impara
Ogni task scrive in `memory/log/`. Le procedure riuscite finiscono in
`memory/playbooks/`. La sessione dopo li rilegge (regola in `CLAUDE.md`).
Memoria = git. `git commit` la memoria ogni settimana.

## Fase 2
- Cron notturno: report trading + bozze contenuti al risveglio.
- Bottoni Approva/Rifiuta su Telegram per le azioni sensibili.
- UI Vercel se serve più della chat.

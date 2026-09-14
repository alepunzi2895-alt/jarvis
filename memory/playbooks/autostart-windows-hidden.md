# Playbook — Avvio automatico Windows di un processo Python, nascosto

## Quando
Serve che uno script Python (bot, daemon) parta da solo a ogni accesso
Windows, senza finestra visibile, con restart automatico se crasha.

## Passi
1. Usa il modulo PowerShell `ScheduledTasks` (`Register-ScheduledTask`),
   non `schtasks.exe` da riga di comando — `schtasks` non espone affatto
   il restart-on-failure, solo l'oggetto/XML del Task Scheduler ce l'ha
   (`New-ScheduledTaskSettingsSet -RestartCount -RestartInterval`).
2. Non lanciare `pythonw.exe` (niente console) diretto come azione del
   task: un processo GUI-subsystem non ha NESSUNO stdio handle, quindi
   `sys.stdout`/`sys.stderr` sono `None`. Se il codice chiama
   `sys.stdout.reconfigure(...)` o anche solo `print()` presto nell'avvio,
   crash immediato e silenzioso (nessuna finestra, nessun log, nessun
   indizio). Fix: wrapper `.vbs` che lancia `pythonw.exe` dentro
   `cmd.exe /c ""<pythonw>" <args> > "<log>" 2>&1"` — il redirect da'
   handle di file veri a stdout/stderr (fixa il crash) e produce un log
   leggibile, l'unico modo di diagnosticare un crash in un processo
   altrimenti invisibile.
3. Nel `.vbs`, `objShell.Run(cmd, 0, True)` — il terzo parametro (
   `bWaitOnReturn`) DEVE essere `True`. Se `False`, Task Scheduler traccia
   solo l'uscita immediata di `wscript.exe` (successo), non quella del
   vero processo Python che gira "dietro" — il restart-on-failure
   configurato sul task non scatterebbe mai se poi il processo crasha
   qualche secondo dopo.
4. Impostazioni del task da NON lasciare ai default:
   `-ExecutionTimeLimit ([TimeSpan]::Zero)` (default 72 ore: ammazzerebbe
   un processo sano dopo 3 giorni), `-AllowStartIfOnBatteries
   -DontStopIfGoingOnBatteries` (se e' un portatile), `-MultipleInstances
   IgnoreNew` (evita che Task Scheduler stesso lanci due copie — non
   protegge pero' da un avvio manuale in parallelo dello stesso script).
5. Trigger `-AtLogOn` sull'utente corrente, `-RunLevel Limited` (niente
   UAC/elevazione — serve comunque la sessione interattiva vera per
   microfono/hotkey/audio, elevare non aiuta e puo' bloccare l'avvio
   silenzioso dietro un prompt UAC).
6. Rendi lo script di setup idempotente (bootstrap venv se manca, `-Force`
   su `Register-ScheduledTask`) e scrivi sempre anche uno script di
   disinstallazione gemello, safe-to-rerun (non deve fallire se il task e'
   gia' assente, non deve uccidere processi vivi ne' toccare i log).

## Limite scoperto (2026-09-14) — leggi PRIMA di un riavvio post-modifica
Una sessione Claude Code **non riesce a terminare** un processo lanciato
da uno Scheduled Task — "Accesso negato" su `Stop-Process`, `taskkill`, e
(silenziosamente, senza uccidere nulla) `Stop-ScheduledTask` sui processi
orfani sotto `pythonw.exe`. Confermato che owner e SessionId del processo
combaciano esattamente con quelli della sessione Claude Code stessa — non
e' un problema di utente/sessione diversi. Causa piu' probabile: EDR
aziendale (vale su macchine in un dominio Windows aziendale) o una
restrizione del token di questa sessione di automazione.

**Conseguenza pratica**: se modifichi il codice di un processo che
l'autostart ha GIA' avviato, farlo ripartire con la versione nuova
richiede o un vero logoff/riavvio di Windows o che l'utente lo chiuda a
mano (Task Manager, lui ha accesso pieno) — non provare a insistere con
altri modi automatici di uccidere il PID, e non serve nemmeno provare
`Stop-ScheduledTask` sperando funzioni meglio la seconda volta. Dillo
subito all'utente invece di far finta che il riavvio sia riuscito.

## Errori da evitare
- Non assumere che "stesso utente Windows" implichi "stessi permessi per
  terminare processi" — su una macchina aziendale non e' garantito.
- Non lanciare `pythonw.exe` diretto senza redirect di stdout/stderr.
- Non lasciare `bWaitOnReturn=False` nel `.vbs` "tanto parte lo stesso" —
  parte, ma il restart-on-failure smette di funzionare in silenzio.

## Ultimo aggiornamento
2026-09-14

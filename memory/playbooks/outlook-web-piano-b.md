# Outlook Web (piano B) — verifica e debug dal vivo

Quando: il piano B Outlook Web (`core/outlook_web.py`) restituisce liste vuote, errori "lettura non riuscita" o "serve di nuovo l'accesso Microsoft".

## Prova veloce (LiveBridge acceso)
```
.venv/Scripts/python.exe -c "from core import outlook_web; print(outlook_web.call_sync('unread'))"
```
Altre azioni: `emails` (count, unread_only), `find` (query), `events` (day ISO, solo lun-ven della settimana corrente).
La prima chiamata dopo un riavvio impiega 20-35 s (avvio del browser e scelta dell'account); le successive 5-15 s.

## Ispezionare il DOM
Il profilo `.browser_profile` e' di LiveBridge: Chromium non lo apre da due processi.
1. Ferma LiveBridge: `Stop-ScheduledTask -TaskPath '\JARVIS\' -TaskName LiveBridge`, poi `Stop-Process` sul python con `core.live_server` nella CommandLine.
2. Script nello scratchpad con `browser.get_agent()` e `outlook_web._ACTIONS[...]` oppure `service_page(...)` + `page.evaluate(...)`. Eseguilo con `python -I`. In JS usa `String.fromCharCode(10)` al posto di `'\n'`: gli heredoc rompono gli escape.
3. Alla fine: `await browser.get_agent()._reset()` e `Start-ScheduledTask -TaskPath '\JARVIS\' -TaskName LiveBridge`.

## Fatti verificati (2026-10-27)
- Usare `https://outlook.cloud.microsoft.mcas.ms`: outlook.office.com va in ciclo `login.microsoftonline.com/common/reprocess`.
- A ogni avvio del browser Microsoft chiede "Selezionare un account": `browser.wait_ready` clicca l'unico account gia' collegato, mai se gli account sono piu' di uno.
- Anche la pagina di login ha `[role=main]`: "pronta" vale solo fuori da login.*.
- Riga mail: prima foglia = avatar (iniziali in grassetto) o icona (area privata Unicode); il mittente ha l'indirizzo nel `title`; l'ora ha la data completa nel `title`.
- Calendario: la data nell'URL viene ignorata; la vista settimana lavorativa ha etichette "Titolo, Dalle 10:05 alle 10:30, Mercoledì, 28 Ottobre, 2026, ...".
- Corpo della mail: `#ReadingPaneContainerId [role=document]`. Aprire una mail la segna come letta.

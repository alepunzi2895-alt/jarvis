# Leggere API interne con la sessione utente (browser JARVIS)

## Quando
Una fonte risponde solo all'utente loggato (non a service principal o token): chat Genie Code su Databricks, Table API ServiceNow.

## Procedura
1. Scoperta: nel Chrome di Alessandro (claude-in-chrome) aprire il sito, `read_network_requests` dopo l'azione UI, poi provare la chiamata con `javascript_tool` (fetch dalla pagina).
2. Token in pagina: Databricks `window.settings.csrfToken` come `X-CSRF-Token`, path `/ajax-api/...` (con `/api/...` risponde 401). ServiceNow `window.g_ck` come `X-UserToken` su `/api/now/table/...`.
3. In JARVIS: `get_agent().evaluate_on(url, ready_js, script, arg)` da un thread con `asyncio.run_coroutine_threadsafe(..., loop)` del processo LiveBridge (vedi `core/genie_code.py`, `core/servicenow.py`). Riusa una scheda gia' aperta su quell'host, altrimenti scheda propria chiusa alla fine.
4. Restituire dalla pagina solo i campi utili (le risposte grezze possono pesare MB: una chat Genie Code ~3,7 MB).
5. Errore "accesso scaduto": aprire il servizio dai Collegamenti della dashboard e completare SSO.

# Verifica dashboard mobile senza servizi reali

1. `node --check web/public/app.js`.
2. Installa se necessari i browser: `.venv/Scripts/python.exe -m playwright install chromium webkit`.
3. `.venv/Scripts/python.exe -m pytest -q tests/test_dashboard_mobile.py`.
   La suite intercetta tutte le richieste e simula i media: nessun audio,
   task o messaggio viene inviato ai servizi reali.
4. Controlla 320x568, 390x844, 844x390 e viewport ridotta per tastiera.
   Pannelli e input devono essere visibili, dock scorrevole, touch target
   almeno 44 px. Il desktop deve mantenere più pannelli.
5. Microfono: niente avvio automatico mobile; attivazione al tap,
   resume AudioContext prima degli await; rifiuto/annullamento permessi,
   lock occupato, cambio app e interruzione audio devono liberare le risorse.
6. Verifica reale separata su Safari iPhone: permessi, tastiera, cuffie,
   blocco/sblocco, ritorno alla pagina e frase italiana. WebKit emulato non
   dimostra il funzionamento del microfono fisico o la latenza completa.

Prima di promettere risposte vocali mobili, verifica la destinazione TTS:
attualmente il bridge parla sul PC. La trascrizione locale non significa
trasporto locale: la dashboard attuale invia gli audio a Turso.

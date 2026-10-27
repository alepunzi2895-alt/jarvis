# Playbook — JARVIS lento

## Quando
Alessandro dice che JARVIS "prima rispondeva in fretta, ora e' lento".

## Passi
1. Alimentazione: `Get-CimInstance Win32_Battery` → `BatteryStatus` 1 = a batteria.
   A batteria whisper su CPU rallenta molto (2026-09: 16 s contro 2 s per segmento).
2. Rete: `Get-NetIPConfiguration` → gateway `172.20.10.x` = hotspot iPhone.
   `Test-Connection 1.1.1.1 -Count 4`: oltre 100 ms tutto cio' che va in rete rallenta
   (edge-tts, meteo, TradePilot, API).
3. Log: `logs/live.log` (`Contesto non aggiornato`, `Campione TradePilot non disponibile`),
   `logs/bot.log` (`Outlook non risponde` / `Outlook occupato`), `logs/voice.log`.
4. Modello e token per chiamata: `.costs.sqlite3` in sola lettura
   (`sqlite3.connect(Path('.costs.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)`),
   tabella `calls`.
5. Misure con script in scratchpad, senza toccare i servizi:
   - API: `client.messages.stream` con `claude-haiku-5-5` (`output_config={"effort": "low"}`)
     e `claude-haiku-4-5`, tempo al primo testo.
   - TTS: `core.voice.tts._edge_tts_audio(frase)` e `synthesize_mp3` (edge + effetti).
   - STT: frase generata con `tts._sapi_audio(...)`, poi `stt.warm_up()` e
     `stt.transcribe_wav(wav)`. Mai registrare dal microfono.
6. Outlook desktop: `Get-Process OUTLOOK` (Responding). Se il bot scrive
   "Outlook occupato" a ogni giro, una chiamata COM e' appesa.

## Valori di riferimento (2026-10-27, hotspot e batteria)
- Haiku 5.5 primo testo 1,9-2,3 s; Haiku 4.5 0,5-0,9 s.
- edge-tts 1,3-6 s a frase (in ufficio 0,3-0,6 s); STT CPU 5,4 s per 6 s di parlato.

## Errori da evitare
- Non riavviare Bot, LiveBridge o VoiceDaemon senza conferma.
- Non stampare valori di `.env`; non scrivere nei `.sqlite3`.
- Non promettere "risolto" senza una misura dopo la modifica.

## Ultimo aggiornamento
2026-10-27

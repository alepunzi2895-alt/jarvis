"""
JARVIS — sintesi vocale. Interfaccia comune (`TTSEngine`) + motore di
default gratuito (edge-tts). Un domani un `ElevenLabsEngine` puo'
implementare la stessa interfaccia (speak/stop/speak_stream) senza toccare
core/voice/daemon.py.
"""

import contextlib
import io
import json
import os
import re
import asyncio
import tempfile
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

import aiohttp
import av
import numpy as np
import sounddevice as sd
import edge_tts

from core import turso
from core.voice import resolve_output_device

# 2026-09-16: cambiata a it-IT-DiegoNeural (non multilingua) per evitare lo
# switch di lingua sulle parole inglesi ricorrenti (GitHub, Teams, ecc.),
# poi RIPORTATA a Giuseppe su richiesta esplicita di Alessandro dopo aver
# sentito Diego: preferisce il tono di Giuseppe e accetta il difetto della
# lingua piuttosto che tenere una voce che non gli piace. Query reale del
# catalogo edge-tts (2026-09-16): solo 4 voci it-IT esistono (Giuseppe
# Multilingual, Diego, Elsa, Isabella) — Giuseppe e' l'UNICA voce
# maschile con quel timbro, non esiste una variante non-multilingua dello
# stesso personaggio. Se lo switch di lingua torna a dare fastidio, le
# uniche alternative reali sono Diego (gia' provato, scartato) o una voce
# femminile (Elsa/Isabella, mai provate).
# 2026-10-14: Alessandro sceglie il campione `8_andrew_film` (voce piu' vicina
# al JARVIS dei film): Andrew Multilingual che parla italiano, rate/pitch
# leggermente ridotti e catena effetti core/voice/voice_fx.py::film.
# JARVIS_TTS_STYLE=none torna all'audio edge-tts senza effetti.
# Poco dopo: "non mi piace l'accento inglese, ci vuole un italiano fluente
# stile JARVIS" -> default Giuseppe (italiano nativo) con la stessa catena film.
VOICE = os.getenv("JARVIS_TTS_VOICE", "it-IT-GiuseppeMultilingualNeural")
RATE = os.getenv("JARVIS_TTS_RATE", "-2%")
PITCH = os.getenv("JARVIS_TTS_PITCH", "-6Hz")
STYLE = os.getenv("JARVIS_TTS_STYLE", "film").strip().lower()
# "xtts": voce da jarvis_voice/refs tramite core/voice/xtts_server.py (processo
# separato in .venv-xtts). Se il server non risponde si ripiega su edge-tts.
ENGINE = os.getenv("JARVIS_TTS_ENGINE", "edge").strip().lower()
XTTS_URL = os.getenv("JARVIS_XTTS_URL", "http://127.0.0.1:8766")
# Import all'avvio: scipy a freddo costa ~2,5 s, non deve pesare sulla prima
# frase pronunciata.
from core.voice import voice_fx  # noqa: E402

# Override a caldo (file non versionato): cambiare voce non richiede di
# riavviare bot, daemon e LiveBridge, che Claude Code non puo' chiudere.
# Esempio: {"voice": "it-IT-GiuseppeMultilingualNeural", "rate": "-4%",
# "pitch": "-10Hz", "style": "film"}. Riletto quando cambia la data del file.
VOICE_OVERRIDE = Path(__file__).resolve().parents[2] / ".tts-voice.json"
_override = {"mtime": None, "data": {}}


def voice_settings() -> dict:
    try:
        mtime = VOICE_OVERRIDE.stat().st_mtime
    except OSError:
        mtime = None
    if mtime != _override["mtime"]:
        try:
            data = json.loads(VOICE_OVERRIDE.read_text(encoding="utf-8")) if mtime else {}
        except (OSError, ValueError):
            data = {}
        _override.update(mtime=mtime, data=data if isinstance(data, dict) else {})
    data = _override["data"]
    return dict(voice=str(data.get("voice") or VOICE), rate=str(data.get("rate") or RATE),
                pitch=str(data.get("pitch") or PITCH), style=str(data.get("style") or STYLE).strip().lower(),
                engine=str(data.get("engine") or ENGINE).strip().lower())


def synthesis_timeout() -> float:
    """XTTS su CPU impiega secondi per frase: 20 s bastano solo a edge-tts."""
    return 60.0 if voice_settings()["engine"] == "xtts" else 20.0


async def _xtts_audio(text: str) -> bytes:
    timeout = aiohttp.ClientTimeout(total=55)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(XTTS_URL + "/tts", json={"text": text}) as response:
            response.raise_for_status()
            return await response.read()


async def _tts_audio(text: str) -> bytes:
    """Audio (MP3 da edge-tts o WAV da XTTS/SAPI) con il motore scelto."""
    if voice_settings()["engine"] == "xtts":
        try:
            return await _xtts_audio(text)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f"(XTTS non disponibile, uso edge-tts: {type(e).__name__})")
    try:
        return await asyncio.wait_for(_edge_tts_audio(text), EDGE_TTS_TIMEOUT_SEC)
    except Exception as e:  # noqa: BLE001 — rete bloccata, proxy, 403, timeout: la voce non deve tacere
        print(f"(edge-tts non disponibile, uso la voce di Windows: {type(e).__name__})")
        return await asyncio.to_thread(_sapi_audio, text)


# Piano B senza rete: voce di sistema Windows (SAPI) scritta in WAV. Dal PC
# Iveco edge-tts a volte non risponde (2026-10-27: TimeoutError e risposta
# muta dalla console). Qualita' inferiore, ma JARVIS parla comunque.
EDGE_TTS_TIMEOUT_SEC = float(os.getenv("JARVIS_EDGE_TTS_TIMEOUT_SEC", "6"))
SAPI_VOICE_HINT = os.getenv("JARVIS_SAPI_VOICE", "Italian")


def _sapi_audio(text: str) -> bytes:
    import win32com.client  # pywin32: gia' nei requisiti per Outlook

    path = Path(tempfile.gettempdir()) / f"jarvis-sapi-{os.getpid()}-{threading.get_ident()}.wav"
    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    for voice in speaker.GetVoices():
        if SAPI_VOICE_HINT.casefold() in voice.GetDescription().casefold():
            speaker.Voice = voice
            break
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    stream.Open(str(path), 3)  # SSFMCreateForWrite
    try:
        speaker.AudioOutputStream = stream
        speaker.Speak(text)
    finally:
        stream.Close()
    try:
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)

# Il servizio edge-tts risponde 403 a caso: misurato il 2026-10-12, 1 richiesta
# su 8 (le altre ok in 0,3-0,6 s), e JARVIS restava muto per quella risposta.
# Causa non isolata: l'orologio del PC e' avanti di ~114 s, ma correggere lo
# skew del token non ha cambiato l'esito. Ritentare subito basta — workaround,
# non fix della causa.
# 2026-10-14: 403 diventato 12 su 12 con edge-tts 7.2.8 (voce muta ovunque,
# promemoria riunione compreso). Il servizio ora richiede il token
# Sec-MS-GEC versione 2, introdotto in edge-tts 7.3.x: requirements >=7.3.1.
_EDGE_TTS_ATTEMPTS = 3


async def _edge_tts_audio(text: str) -> bytes:
    for attempt in range(_EDGE_TTS_ATTEMPTS):
        try:
            buf = io.BytesIO()
            cfg = voice_settings()
            async for chunk in edge_tts.Communicate(text, cfg["voice"], rate=cfg["rate"], pitch=cfg["pitch"]).stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            return buf.getvalue()
        except aiohttp.WSServerHandshakeError as e:
            if e.status != 403 or attempt == _EDGE_TTS_ATTEMPTS - 1:
                raise
            await asyncio.sleep(0.2)


def apply_style(data: np.ndarray, samplerate: int) -> np.ndarray:
    """Effetti della voce scelta su audio decodificato (frames, canali).
    Uscita mono float32 (frames, 1), pronta per sounddevice."""
    if voice_settings()["style"] != "film":
        return data
    mono = data.mean(axis=1) if data.ndim == 2 else data
    return voice_fx.film(mono, samplerate).astype(np.float32)[:, None]


def _encode_mp3(data: np.ndarray, samplerate: int) -> bytes:
    out = io.BytesIO()
    with av.open(out, "w", format="mp3") as container:
        stream = container.add_stream("libmp3lame", rate=samplerate, layout="mono")
        stream.bit_rate = 64000
        pcm = np.ascontiguousarray(data.reshape(1, -1), dtype=np.float32)
        frame = av.AudioFrame.from_ndarray(pcm, format="flt", layout="mono")
        frame.sample_rate = samplerate
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return out.getvalue()


async def synthesize_mp3(text: str) -> bytes:
    """MP3 con la voce scelta per chi riproduce altrove (dashboard privata)."""
    raw = await _tts_audio(text)
    # Il WAV di XTTS va comunque ricodificato: ~10 volte piu' pesante dell'MP3.
    if not raw or (voice_settings()["style"] != "film" and not raw.startswith(b"RIFF")):
        return raw

    def styled() -> bytes:
        data, rate = EdgeTTSEngine._decode(io.BytesIO(raw))
        return _encode_mp3(apply_style(data, rate), rate)

    return await asyncio.to_thread(styled)

# --------------------------------------------------------------------------- stato "sto parlando" (dashboard)
#
# La dashboard web (browser) non ha modo di sapere quando JARVIS sta parlando
# davvero: l'audio esce dagli altoparlanti del PC via un processo Python
# separato, non nel browser. Un flag condiviso su Turso (stesso DB del
# second brain/coda task) e' il modo piu' semplice per farlo sapere alla
# dashboard, che lo legge in polling — richiesta esplicita di Alessandro:
# la bolla centrale deve muoversi/cambiare colore quando JARVIS parla,
# qualunque sia il canale che ha innescato la voce (Telegram, dashboard,
# daemon nativo: passano tutti da qui).

_speaking_flag_bootstrapped = False


def _bootstrap_speaking_flag() -> None:
    global _speaking_flag_bootstrapped
    if _speaking_flag_bootstrapped:
        return
    try:
        turso.execute(
            "CREATE TABLE IF NOT EXISTS runtime_flags ("
            "key TEXT PRIMARY KEY, value TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
    except Exception:  # noqa: BLE001 — la dashboard non vedra' l'indicatore, la voce deve uscire comunque
        pass
    _speaking_flag_bootstrapped = True


def _set_speaking(flag: bool) -> None:
    if not turso.ENABLED:
        return
    _bootstrap_speaking_flag()
    try:
        turso.execute(
            "INSERT INTO runtime_flags (key, value, updated_at) VALUES ('speaking', ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            ["1" if flag else "0"],
        )
    except Exception:  # noqa: BLE001 — best-effort, un blip di rete non deve mai bloccare il parlato
        pass


def _set_speaking_bg(flag: bool) -> None:
    """Fire-and-forget in un thread separato: la scrittura Turso non deve mai
    ritardare l'inizio/la fine del parlato reale (sincrona o dentro un loop
    asyncio, speak()/speak_stream() la chiamano entrambe allo stesso modo)."""
    threading.Thread(target=_set_speaking, args=(flag,), daemon=True).start()


class TTSEngine:
    def speak(self, text: str) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    async def speak_stream(self, sentences: AsyncIterator[str], stop_event: threading.Event) -> None:
        raise NotImplementedError


class EdgeTTSEngine(TTSEngine):
    """Gratis, nessuna API key. Sintetizza in mp3, decodifica con PyAV
    (già una dipendenza di faster-whisper) e riproduce con sounddevice."""

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        path = self._synthesize(text)
        _set_speaking_bg(True)
        try:
            data, samplerate = self._decode(path)
            data = apply_style(data, samplerate)
            sd.play(data, samplerate, device=resolve_output_device())
            sd.wait()
        finally:
            _set_speaking_bg(False)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass  # Windows: il file puo' restare bloccato un istante in più

    def stop(self) -> None:
        sd.stop()

    async def speak_stream(self, sentences: AsyncIterator[str], stop_event: threading.Event) -> None:
        """Consuma le frasi generate da claude_api.run_voice_streaming() e le
        parla una per volta, sintetizzando la frase N+1 mentre la N sta
        ancora suonando (coda NON limitata: produttore e consumatore sono
        coroutine indipendenti, il lookahead avviene comunque senza bisogno
        di un limite — un maxsize=1 sembra piu' "naturale" per un lookahead
        di una sola frase, ma puo' restare in deadlock se il consumer esce
        mentre il producer e' bloccato su queue.put(): anche il suo
        `finally: queue.put(None)` si bloccherebbe di nuovo sulla stessa
        coda piena)."""
        queue: asyncio.Queue = asyncio.Queue()

        async def producer() -> None:
            try:
                async for sentence in sentences:
                    if stop_event.is_set():
                        continue  # continua comunque a drenare lo stream: run_voice_streaming deve completare
                    try:
                        audio = await self._synthesize_to_array(sentence)
                    except Exception as e:  # noqa: BLE001 — una frase persa non deve abortire la risposta
                        print(f"(sintesi TTS fallita per una frase, salto: {e})")
                        continue
                    if audio is not None and not stop_event.is_set():
                        await queue.put(audio)
            finally:
                await queue.put(None)

        producer_task = asyncio.create_task(producer())
        _set_speaking_bg(True)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if not stop_event.is_set():
                    data, samplerate = item
                    await asyncio.to_thread(self._play_blocking, data, samplerate, stop_event)
        finally:
            _set_speaking_bg(False)
            if not producer_task.done():
                producer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer_task  # ripropaga un'eccezione reale del producer (es. errore di autenticazione edge-tts)

    def _play_blocking(self, data: np.ndarray, samplerate: int, stop_event: threading.Event) -> None:
        if stop_event.is_set():
            return
        sd.play(data, samplerate, device=resolve_output_device())
        sd.wait()

    async def _synthesize_to_array(self, text: str) -> tuple[np.ndarray, int] | None:
        text = text.strip()
        if not text:
            return None
        buf = io.BytesIO(await _tts_audio(text))

        def decoded():
            data, rate = self._decode(buf)
            return apply_style(data, rate), rate

        return await asyncio.to_thread(decoded)

    def _synthesize(self, text: str) -> Path:
        audio = asyncio.run(_tts_audio(text))
        fd, tmp_path = tempfile.mkstemp(suffix=".wav" if audio.startswith(b"RIFF") else ".mp3")
        os.close(fd)
        path = Path(tmp_path)
        path.write_bytes(audio)
        return path

    @staticmethod
    def _decode(source: Path | BinaryIO) -> tuple[np.ndarray, int]:
        container = av.open(str(source) if isinstance(source, Path) else source)
        try:
            stream = container.streams.audio[0]
            frames = [f.to_ndarray() for f in container.decode(stream)]
            data = np.concatenate(frames, axis=1).T
            rate = stream.rate
        finally:
            # Su Windows il file va chiuso esplicitamente subito, altrimenti
            # resta bloccato quando si prova a cancellarlo poco dopo.
            container.close()
        return data, rate


def get_engine() -> TTSEngine:
    return EdgeTTSEngine()


# --------------------------------------------------------------------------- voce locale (risposte non-vocali)
#
# "Deve rispondermi sempre vocalmente" (2026-09-14): le risposte di QUALSIASI
# canale locale (Telegram, dashboard web) escono anche dagli altoparlanti del
# PC, non solo il canale vocale nativo. Un solo punto condiviso, cosi' bot.py
# e core/web_bridge.py non duplicano motore/pulizia markdown/interruttore.

_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_SYMBOLS_RE = re.compile(r"[*_`#]+")
# Stesso confine di frase usato da core/claude_api.py::run_voice_streaming
# per lo streaming vocale — riusato qui per lo stesso motivo: iniziare a
# sentire la prima frase mentre le successive sintetizzano ancora, invece
# di aspettare l'intera risposta come un unico file audio.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_shared_engine: TTSEngine | None = None


def clean_for_speech(text: str) -> str:
    """Copia ripulita per il TTS — il testo mostrato all'utente non cambia."""
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_SYMBOLS_RE.sub("", text)
    return text.strip()


# --------------------------------------------------------------------------- barge-in (Telegram/dashboard)
#
# Fino al 2026-09-15 questo canale non poteva mai essere interrotto ("nessun
# canale qui ha un hotkey" — vero per Telegram, ma la dashboard ha da oggi un
# mic a mani libere che PUO' captare una nuova parola d'attivazione mentre
# JARVIS sta ancora parlando, esattamente come il daemon vocale nativo
# (core/voice/daemon.py::_speak_with_interrupt). _current_stop_event rende
# quell'evento raggiungibile dall'esterno (web_bridge.py) invece di restare
# locale alla singola chiamata come prima.
_current_stop_event: threading.Event | None = None
_stop_event_lock = threading.Lock()


def stop_current_speech() -> None:
    """Interrompe subito la voce in corso su questo canale, se ce n'e' una —
    no-op innocuo se JARVIS non sta parlando. sd.stop() ferma l'audio gia'
    in uscita dagli altoparlanti; l'Event impedisce che le frasi successive
    (gia' in coda/sintesi) vengano comunque suonate dopo."""
    with _stop_event_lock:
        event = _current_stop_event
    if event is not None:
        event.set()
    if _shared_engine is not None:
        _shared_engine.stop()


async def _speak_sentence_stream(engine: TTSEngine, text: str, stop_event: threading.Event) -> None:
    async def _sentences():
        for part in _SENTENCE_SPLIT_RE.split(text):
            part = part.strip()
            if part:
                yield part

    await engine.speak_stream(_sentences(), stop_event)


def _speak_sync(text: str) -> None:
    """2026-09-15: usa speak_stream() (frase per frase, sintesi della
    prossima mentre la corrente sta gia' suonando) invece di speak() (un
    unico file per l'intera risposta) — richiesta esplicita di Alessandro
    di ridurre il tempo prima di sentire la prima parola, stesso guadagno
    gia' sfruttato dal canale vocale nativo per la voce in streaming da
    Claude, qui applicato a un testo gia' completo (Telegram/dashboard non
    generano la risposta a pezzi come l'API diretta della voce)."""
    global _shared_engine, _current_stop_event
    text = clean_for_speech(text)
    if not text:
        return
    if _shared_engine is None:
        _shared_engine = get_engine()
    stop_event = threading.Event()
    with _stop_event_lock:
        _current_stop_event = stop_event
    try:
        asyncio.run(_speak_sentence_stream(_shared_engine, text, stop_event))
    except Exception as e:  # noqa: BLE001 — la voce locale non deve mai far fallire la risposta testuale
        print(f"(voce locale fallita, ignorata: {e})")
    finally:
        with _stop_event_lock:
            if _current_stop_event is stop_event:
                _current_stop_event = None


def speak_if_enabled(text: str) -> None:
    """Fire-and-forget (thread): non blocca il loop asyncio chiamante.
    Rispetta lo stesso interruttore /voce on|off del daemon vocale."""
    from core.claude_bridge import load_state  # import qui: evita import circolare a freddo

    if load_state().get("voice_enabled", True):
        asyncio.get_running_loop().run_in_executor(None, _speak_sync, text)

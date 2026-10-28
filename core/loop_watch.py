"""Sorvegliante dell'event loop di LiveBridge.

2026-10-28: "buongiorno" a voce con il primo audio dopo 28-50 s, mentre la
stessa sintesi edge-tts fuori da LiveBridge impiegava 1,1 s. Se qualcosa
blocca il loop (codice sincrono, Playwright, librerie lente), voce, eventi e
WebSocket si fermano tutti insieme. Questo thread se ne accorge e scrive nel
log lo stack del thread del loop, cosi' il colpevole ha un nome.
"""
import logging
import sys
import threading
import time
import traceback

LOG = logging.getLogger(__name__)
THRESHOLD_SEC = 2.0
_MIN_GAP_SEC = 60  # al massimo uno stack al minuto: il log non deve esplodere


def start(loop) -> threading.Thread:
    """Avvia il sorvegliante per `loop` (chiamare dal thread del loop)."""
    state = {"beat": time.monotonic(), "loop_thread": threading.get_ident(), "logged": 0.0}

    def beat():
        state["beat"] = time.monotonic()
        loop.call_later(0.25, beat)

    loop.call_soon(beat)

    def watch():
        while not loop.is_closed():
            time.sleep(0.5)
            stalled = time.monotonic() - state["beat"]
            if stalled < THRESHOLD_SEC or time.monotonic() - state["logged"] < _MIN_GAP_SEC:
                continue
            frame = sys._current_frames().get(state["loop_thread"])
            stack = "".join(traceback.format_stack(frame)) if frame else "(stack non disponibile)"
            LOG.warning("Event loop fermo da %.1f s, sta eseguendo:\n%s", stalled, stack)
            state["logged"] = time.monotonic()

    thread = threading.Thread(target=watch, name="loop-watch", daemon=True)
    thread.start()
    return thread

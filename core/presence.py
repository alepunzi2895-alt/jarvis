"""
JARVIS — presenza proattiva: riconosce quando Alessandro si siede alla
scrivania (webcam + riconoscimento volto gia' esistente, core/voice/
face_id.py) e lo saluta da solo, invece di rispondere solo su richiesta
esplicita — richiesta esplicita sua (2026-09-16).

Disattivo di default (JARVIS_PRESENCE_INTERVAL_SEC assente/0): attivare la
webcam periodicamente senza che lui chieda nulla e' un compromesso di
privacy diverso da "webcam solo su richiesta" gia' in uso altrove nel
repo — va acceso di proposito, non di default.

Un solo saluto per transizione assente->presente, non uno ad ogni ciclo:
_ABSENCE_STREAK evita che un singolo frame perso (luce, angolo webcam)
faccia sembrare "assente" chi in realta' e' sempre li', e COOLDOWN_SEC
evita di risalutare a raffica se il riconoscimento sfarfalla proprio al
momento della transizione.
"""

from __future__ import annotations

import os
import random
import time

from core.voice import camera, face_id

INTERVAL_SEC = int(os.getenv("JARVIS_PRESENCE_INTERVAL_SEC", "0") or "0")
ENABLED = INTERVAL_SEC > 0

_ABSENCE_STREAK = 3  # cicli consecutivi senza il volto prima di considerarlo "andato via"
COOLDOWN_SEC = 1800  # non risalutare piu' spesso di cosi', anche se sfarfalla

_GREETINGS = [
    "Bentornato, Signore.",
    "Eccola, Signore. Tutto pronto.",
    "Buongiorno di nuovo, Signore.",
]


class PresenceTracker:
    def __init__(self) -> None:
        self._absence_streak = 0
        self._present = False
        self._last_greet_ts = float("-inf")

    def check(self, now: float | None = None) -> str | None:
        """Cattura un frame e aggiorna lo stato. Ritorna un saluto SOLO alla
        transizione assente->presente rispettando il cooldown, altrimenti
        None. `now` e' iniettabile per i test (altrimenti time.time())."""
        if now is None:
            now = time.time()
        if not face_id.is_enrolled():
            return None

        frame = camera.capture_frame_raw()
        if frame is None:
            return None
        name, _confidence = face_id.recognize(frame)
        recognized = name is not None

        if not recognized:
            self._absence_streak += 1
            if self._absence_streak >= _ABSENCE_STREAK:
                self._present = False
            return None

        self._absence_streak = 0
        if self._present:
            return None  # gia' presente, niente da annunciare
        self._present = True
        if now - self._last_greet_ts < COOLDOWN_SEC:
            return None
        self._last_greet_ts = now
        return random.choice(_GREETINGS)

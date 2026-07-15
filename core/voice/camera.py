"""
JARVIS — cattura webcam nativa per il daemon vocale.

Il pannello camera della dashboard web usa getUserMedia dal browser; il
daemon vocale non ha un browser, quindi cattura un frame direttamente dalla
webcam del PC con OpenCV e lo passa allo stesso identico canale
image_b64 già usato da core/claude_bridge.py (nessuna nuova dipendenza di
visione, Claude legge il file con il suo Read tool).
"""

import base64
import re

import cv2

CAMERA_INTENT_RE = re.compile(
    r"\b(webcam|telecamera|fotocamera|camera)\b.*\b(vedi|guarda|guardi|mostra|cosa)\b"
    r"|\b(vedi|guarda|guardi|cosa vedi)\b.*\b(webcam|telecamera|fotocamera|camera)\b",
    re.IGNORECASE,
)


def wants_camera(text: str) -> bool:
    return bool(CAMERA_INTENT_RE.search(text))


def capture_frame_b64(device_index: int = 0) -> str | None:
    """Cattura un singolo frame dalla webcam, ritorna JPEG base64 o None se non disponibile."""
    cap = cv2.VideoCapture(device_index)
    try:
        if not cap.isOpened():
            return None
        # La prima lettura dopo l'apertura è spesso un frame vecchio/nero
        # (buffer non ancora popolato) — se ne scartano un paio.
        for _ in range(3):
            cap.read()
        ok, frame = cap.read()
        if not ok:
            return None
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            return None
        return base64.b64encode(buf.tobytes()).decode("ascii")
    finally:
        cap.release()

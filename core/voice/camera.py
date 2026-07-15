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

_CAM_WORDS = r"webcam|telecamera|fotocamera|camera"
_CAM_VERBS = r"vedi|guarda|guardi|mostra|mostri|cosa|apri|apra|accendi|accenda|attiva|attivi"

# Copre sia "webcam... cosa vedi" sia il semplice "apri/accendi la webcam" —
# quest'ultimo prima non veniva riconosciuto (nessun "vedi"/"cosa" nella
# frase), quindi cadeva come task generico a Claude, che non avendo modo di
# "aprire" davvero la webcam finiva per improvvisare un'azione sbagliata
# (es. aprire un browser). Con questo pattern la richiesta scatta sempre la
# cattura locale, a prescindere dal verbo usato.
#
# "scatta/fotografa/fai una foto" innescano la cattura da soli, anche SENZA
# la parola "webcam" — bug reale riscontrato: "scatta e dimmi cosa vedi"
# non conteneva nessuna delle due parti sopra, quindi cadeva a Claude che,
# senza immagine, ha improvvisato aprendo un browser verso la dashboard
# locale. "Scattare una foto" per JARVIS puo' significare solo la webcam.
CAMERA_INTENT_RE = re.compile(
    rf"\b({_CAM_WORDS})\b.*\b({_CAM_VERBS})\b|\b({_CAM_VERBS})\b.*\b({_CAM_WORDS})\b"
    r"|\bscatta\w*\b|\bfotografa\w*\b|\bfai\w*\s+una\s+foto\b",
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

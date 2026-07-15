"""
JARVIS — riconoscimento volto locale (OpenCV, offline, nessun cloud).

Un classificatore LBPH (Local Binary Patterns Histograms, cv2.face) addestrato
su qualche decina di frame della webcam di Alessandro. Serve solo a
personalizzare la risposta ("la persona nella foto sembra essere Alessandro"),
NON e' un sistema di sicurezza/autenticazione — un LBPH allenato su ~20 frame
e' facilmente ingannabile (foto stampata, luce diversa, un'altra persona
somigliante) e non va mai usato per decisioni che contano davvero.

Un solo volto arruolato per ora ("alessandro"); la struttura a più label
(labels.json) regge comunque se in futuro se ne aggiungono altri.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import cv2
import numpy as np

JARVIS_HOME = Path(os.getenv("JARVIS_HOME", Path(__file__).parent.parent.parent)).resolve()
DATA_DIR = JARVIS_HOME / ".face_data"
MODEL_PATH = DATA_DIR / "lbph_model.yml"
LABELS_PATH = DATA_DIR / "labels.json"

# La cascade Haar viene dal repo (core/voice/data/), non da cv2.data.haarcascades:
# la wheel di opencv-contrib-python installata (5.0.0) non include piu' i file
# XML in cv2/data/ (cartella presente ma vuota) — dipendere da un file spedito
# col pacchetto pip si e' rivelato fragile tra versioni diverse di OpenCV.
CASCADE_PATH = Path(__file__).parent / "data" / "haarcascade_frontalface_default.xml"

# LBPH: piu' basso = match piu' sicuro (e' una distanza, non una probabilita').
# 75 e' un valore soglia comune per LBPH addestrato su pochi campioni; sopra
# quella soglia si preferisce dire "non riconosciuto" piuttosto che sbagliare.
CONFIDENCE_THRESHOLD = float(os.getenv("JARVIS_FACE_CONFIDENCE_MAX", "75"))

_face_cascade: cv2.CascadeClassifier | None = None


def _get_cascade() -> cv2.CascadeClassifier:
    global _face_cascade
    if _face_cascade is None:
        _face_cascade = cv2.CascadeClassifier(str(CASCADE_PATH))
    return _face_cascade


def _detect_face(frame_bgr: np.ndarray) -> np.ndarray | None:
    """Ritaglia il volto piu' grande rilevato nel frame (scala di grigi,
    formato atteso da LBPH), o None se non ne trova nessuno."""
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    faces = _get_cascade().detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(80, 80))
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    return cv2.resize(gray[y : y + h, x : x + w], (200, 200))


def _load_labels() -> dict[str, int]:
    if LABELS_PATH.exists():
        return json.loads(LABELS_PATH.read_text())
    return {}


def is_enrolled() -> bool:
    return MODEL_PATH.exists() and LABELS_PATH.exists()


def enroll_from_frames(frames: list[np.ndarray], label: str = "alessandro") -> int:
    """Rileva un volto in ciascun frame e (ri)addestra il modello. Ritorna
    quanti campioni utili sono stati trovati (0 = nessun volto visibile)."""
    faces = [f for f in (_detect_face(fr) for fr in frames) if f is not None]
    if not faces:
        return 0

    labels_map = _load_labels()
    if label not in labels_map:
        labels_map[label] = len(labels_map)
    label_id = labels_map[label]

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    if MODEL_PATH.exists():
        recognizer.read(str(MODEL_PATH))
        recognizer.update(faces, np.array([label_id] * len(faces)))
    else:
        recognizer.train(faces, np.array([label_id] * len(faces)))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    recognizer.write(str(MODEL_PATH))
    LABELS_PATH.write_text(json.dumps(labels_map))
    return len(faces)


def recognize(frame_bgr: np.ndarray) -> tuple[str | None, float]:
    """Ritorna (nome, confidenza) se riconosce un volto arruolato con
    sufficiente sicurezza, altrimenti (None, -1)."""
    if not is_enrolled():
        return None, -1.0
    face = _detect_face(frame_bgr)
    if face is None:
        return None, -1.0

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.read(str(MODEL_PATH))
    label_id, confidence = recognizer.predict(face)
    if confidence > CONFIDENCE_THRESHOLD:
        return None, confidence

    for name, lid in _load_labels().items():
        if lid == label_id:
            return name, confidence
    return None, confidence


def recognize_file(path: str | Path) -> tuple[str | None, float]:
    frame = cv2.imread(str(path))
    if frame is None:
        return None, -1.0
    return recognize(frame)


def capture_and_enroll(
    device_index: int = 0, n_frames: int = 20, label: str = "alessandro"
) -> tuple[int, str | None]:
    """Cattura n_frames dalla webcam nel giro di qualche secondo e addestra
    il modello. Ritorna (campioni_validi, errore)."""
    cap = cv2.VideoCapture(device_index)
    try:
        if not cap.isOpened():
            return 0, "webcam non disponibile"
        for _ in range(3):  # scarta i primi frame (buffer non ancora popolato)
            cap.read()
        frames = []
        for _ in range(n_frames):
            ok, frame = cap.read()
            if ok:
                frames.append(frame)
            time.sleep(0.15)
    finally:
        cap.release()

    count = enroll_from_frames(frames, label=label)
    if count == 0:
        return 0, "nessun volto rilevato nei frame catturati — riprova piu' vicino e illuminato"
    return count, None

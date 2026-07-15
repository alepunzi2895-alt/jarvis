import os

import sounddevice as sd


def resolve_input_device() -> int | None:
    """Risolve JARVIS_MIC_DEVICE (sottostringa case-insensitive del nome) nel
    device di sounddevice corrispondente. None = usa il default di sistema.

    Windows cambia il device di default quando colleghi/scolleghi una cuffia
    (es. una Jabra) — pinnare per nome evita di ascoltare in silenzio dal
    device sbagliato senza accorgersene.
    """
    name_hint = os.getenv("JARVIS_MIC_DEVICE", "").strip().lower()
    if not name_hint:
        return None
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and name_hint in d["name"].lower():
            return i
    return None

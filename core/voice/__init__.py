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


def resolve_output_device() -> int | None:
    """Come resolve_input_device, ma per l'uscita audio (JARVIS_SPEAKER_DEVICE).

    Stesso problema, lato opposto: Windows può cambiare il device di
    riproduzione di default (es. passa a delle cuffie/monitor HDMI) e la
    voce di JARVIS finirebbe a suonare in un posto che l'utente non sta
    ascoltando, senza nessun errore che lo segnali.
    """
    name_hint = os.getenv("JARVIS_SPEAKER_DEVICE", "").strip().lower()
    if not name_hint:
        return None
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0 and name_hint in d["name"].lower():
            return i
    return None

"""Avanzamento dei comandi lunghi, a voce e a schermo.

Richiesta di Alessandro del 2026-10-28: rispondere subito ("intanto verifico
mail e calendario, vediamo cosa la aspetta oggi"), dire che parte un task se
la risposta richiede tempo, dare una percentuale progressiva e mostrarla a
schermo mentre JARVIS lavora.

Chi lavora (briefing, giri di strumenti del modello) chiama `report()`; chi
ascolta (LiveBridge) installa un reporter con `bind()`. La ContextVar passa da
sola nei thread di asyncio.to_thread, quindi intents e briefing non devono
ricevere parametri in piu'. Senza reporter installato `report()` non fa nulla.
"""
import contextvars
import re

_reporter = contextvars.ContextVar("jarvis_progress", default=None)

# Prima frase detta subito se la risposta non e' gia' partita: specifica quando
# la domanda dice cosa sta per succedere, generica altrimenti.
_ACKS = (
    (r"buongiorno|briefing|cosa (mi aspetta|ho) oggi|giornata", "Intanto verifico mail e calendario, vediamo cosa la aspetta oggi."),
    (r"\b(mail|posta|email)\b", "Controllo la posta, un momento."),
    (r"calendario|agenda|riunion|impegn", "Guardo il calendario."),
    (r"progett", "Passo in rassegna i progetti."),
    (r"iveco|databricks|\bjob\b|deploy|recap|ticket", "Avvio il controllo sui sistemi Iveco, ci vuole qualche secondo."),
    (r"analizz|analisi|confront|statistic|pianific|strateg", "Avvio l'analisi, le dico man mano a che punto sono."),
    (r"meteo|tempo fa|piove", "Controllo il meteo."),
)
GENERIC_ACK = "Ci lavoro, un momento."

TOOL_LABELS = {
    "read_file": "leggo un file", "write_file": "scrivo un file", "list_dir": "guardo le cartelle",
    "run_command": "eseguo un comando", "recall_memory": "consulto la memoria", "list_emails": "controllo la posta",
    "read_email": "leggo una mail", "get_project_status": "controllo i progetti", "get_weather_forecast": "controllo il meteo",
}


def bind(reporter):
    """Installa `reporter(label, percent)` per il comando corrente; ritorna il token per reset()."""
    return _reporter.set(reporter)


def reset(token) -> None:
    _reporter.reset(token)


def report(label: str, percent: int | None = None) -> None:
    reporter = _reporter.get()
    if reporter is None:
        return
    try:
        reporter(label, None if percent is None else max(0, min(100, int(percent))))
    except Exception:  # noqa: BLE001 — l'avanzamento e' un di piu', mai un errore per chi lavora
        pass


def current():
    """Reporter attivo, da catturare prima di passare a thread che non ereditano il contesto."""
    return _reporter.get()


def ack_for(prompt: str) -> str:
    text = (prompt or "").casefold()
    return next((phrase for pattern, phrase in _ACKS if re.search(pattern, text)), GENERIC_ACK)


def tool_label(name: str) -> str:
    return TOOL_LABELS.get(name, name.replace("_", " "))


def tool_percent(step: int) -> int:
    """Strumenti del modello: numero totale ignoto, la percentuale sale e rallenta senza arrivare a 100."""
    return min(90, 15 + 75 - int(75 * 0.65 ** step))

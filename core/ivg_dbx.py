"""Accesso in sola lettura a `IVGAgent/tools/dbx.py` per le sessioni delegate da JARVIS.

Le sessioni Claude Code avviate dal pannello IVECO non possono rispondere a
una richiesta di conferma, quindi non ricevono `tools/dbx.py` direttamente
(avvia job, importa notebook, esegue SQL di scrittura). Ricevono solo questo
script, con gli stessi argomenti, limitato ai comandi di lettura e a SQL di
sola lettura (stesso controllo di core/databricks.py).

Uso: python core/ivg_dbx.py [--env test|prod] <comando> [argomenti]
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
IVG_ROOT = Path(__file__).resolve().parents[2] / "IVGAgent"
READ_COMMANDS = {
    "whoami", "catalogs", "schemas", "tables", "describe", "ls", "cat", "jobs",
    "run-status", "run-output", "genie-spaces", "genie-ask", "warehouses",
    "clusters", "env-catalog", "sql",
}


def normalize(args):
    """`--opzione=valore` diventa due argomenti: il controllo vede cio' che vede argparse."""
    out = []
    for arg in args:
        out.extend(arg.split("=", 1) if arg.startswith("--") and "=" in arg else [arg])
    return out


def check(args):
    """Ritorna il messaggio di rifiuto, oppure None se il comando e' di lettura."""
    rest = normalize(args)
    if rest[:1] == ["--env"]:
        if len(rest) < 2 or rest[1] not in {"test", "prod"}:
            return "Ambiente ammesso: --env test oppure --env prod."
        rest = rest[2:]
    if not rest or rest[0] not in READ_COMMANDS:
        return ("Comando non consentito in questa sessione: solo lettura "
                f"({', '.join(sorted(READ_COMMANDS))}). Avvio job, import e scritture vanno fatti da Alessandro.")
    if rest[0] != "sql":
        return None
    # Opzioni esatte: argparse accetta anche abbreviazioni (--fi, --cs).
    if any(a.startswith("-") and a not in {"--file", "--limit", "--catalog", "--schema", "--json"} for a in rest[1:]):
        return "Opzioni sql ammesse: --file, --limit, --catalog, --schema, --json (niente --csv)."
    from core.databricks import _is_read_only_sql
    if "--file" in rest:
        index = rest.index("--file")
        path = (IVG_ROOT / rest[index + 1]).resolve() if index + 1 < len(rest) else None
        if not path or IVG_ROOT not in path.parents or not path.is_file():
            return "--file deve indicare un file .sql esistente dentro IVGAgent."
        statement = path.read_text(encoding="utf-8")
    else:
        options = {"--limit", "--catalog", "--schema"}
        positional = [a for i, a in enumerate(rest[1:], 1)
                      if not a.startswith("--") and rest[i - 1] not in options]
        statement = positional[0] if positional else ""
    if not _is_read_only_sql(statement):
        return "Solo una query di lettura (SELECT/SHOW/DESCRIBE/EXPLAIN/WITH), una istruzione."
    return None


def main(args):
    args = normalize(args)
    refusal = check(args)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    return subprocess.run([sys.executable, str(IVG_ROOT / "tools" / "dbx.py"), *args], cwd=IVG_ROOT).returncode


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main(sys.argv[1:]))

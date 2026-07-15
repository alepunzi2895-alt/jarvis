"""
JARVIS — istanza condivisa di SystemExecutor.

Estratta in un modulo a se' (invece di vivere dentro bot.py) perche' serve a
piu' processi/moduli: bot.py, core/web_bridge.py (stesso processo di bot.py)
e core/voice/daemon.py (processo separato, ottiene una propria istanza
locale — nessuno stato condiviso tra processi diversi, solo stessa
configurazione). Non importa da core/claude_bridge.py per evitare un import
circolare (claude_bridge -> executor_singleton -> claude_bridge).
"""

import os
from pathlib import Path

from core.obsidian import ObsidianVault
from core.system_executor import SystemExecutor

JARVIS_HOME = Path(os.getenv("JARVIS_HOME", Path(__file__).parent.parent)).resolve()
VAULT_PATH = os.getenv("JARVIS_VAULT_PATH", str(JARVIS_HOME / "jarvis"))
vault = ObsidianVault(VAULT_PATH) if Path(VAULT_PATH).is_dir() else None

_extra_dirs = [p.strip() for p in os.getenv("JARVIS_ALLOWED_DIRS", "").split(",") if p.strip()]
executor = SystemExecutor(allowed_dirs=[JARVIS_HOME, *_extra_dirs], vault=vault)

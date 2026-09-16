"""
JARVIS — bozze mail Outlook da un blocco ```mail_draft``` emesso da Claude.
Stesso pattern di core/browser.py/core/system_actions.py: Claude emette il
blocco in fondo alla risposta, extract_and_execute() lo estrae, esegue,
ripulisce il testo.

MAI un invio reale: core/outlook.py::create_draft_email() chiama solo
.Save(), mai .Send() — coerente con la regola "mai inviare messaggi senza
conferma esplicita" gia' in CLAUDE.md, qui estesa a qualunque destinatario
(non solo clienti).
"""

from __future__ import annotations

import json
import re

from core import outlook

MAIL_DRAFT_BLOCK_RE = re.compile(r"```mail_draft\s*\n(.*?)\n```", re.DOTALL)


async def extract_and_execute(text: str) -> str:
    matches = list(MAIL_DRAFT_BLOCK_RE.finditer(text))
    if not matches:
        return text

    outcomes: list[str] = []
    for m in matches:
        try:
            action = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue

        to = (action.get("to") or "").strip()
        body = (action.get("body") or "").strip()
        subject = (action.get("subject") or "").strip()
        if not to or not body:
            continue

        try:
            outcomes.append(await outlook.create_draft_email(to, subject, body))
        except outlook.OutlookError as e:
            outcomes.append(str(e))

    cleaned = MAIL_DRAFT_BLOCK_RE.sub("", text).strip()
    if outcomes:
        cleaned = f"{cleaned}\n\n{' '.join(outcomes)}".strip()
    return cleaned

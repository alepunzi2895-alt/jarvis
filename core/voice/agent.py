"""La voce PC usa gli stessi strumenti e la stessa memoria della dashboard."""
import asyncio
from dataclasses import dataclass

from core.live_server import Engine

_engine = Engine()
_history = {}


@dataclass
class VoiceResult:
    text: str = ''
    cost: float = 0


async def sentences(prompt, workspace, image, result):
    queue = asyncio.Queue()
    _history.setdefault('_focus', workspace)

    async def run():
        try:
            response = await _engine.respond(prompt, image, _history, queue.put)
            result.text, result.cost = response['result'], response['cost_usd']
        finally:
            await queue.put(None)

    worker = asyncio.create_task(run())
    try:
        while (line := await queue.get()) is not None:
            yield line
        await worker  # propaga l'errore senza trasformarlo in risposta vuota
    finally:
        if not worker.done():
            worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

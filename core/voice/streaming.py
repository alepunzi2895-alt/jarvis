"""Frasi incrementali senza leggere blocchi di controllo o JSON."""

import re


class SentenceBuffer:
    def __init__(self):
        self.buffer = ""
        self.hidden = False

    def feed(self, delta: str) -> list[str]:
        if self.hidden:
            return []
        self.buffer += delta
        if "```" in self.buffer:
            self.buffer = self.buffer.split("```", 1)[0]
            self.hidden = True
            visible = self.buffer.strip()
            self.buffer = ""
            return [visible] if visible else []
        parts = re.split(r"(?<=[.!?])\s+|\n+", self.buffer)
        self.buffer = "" if self.hidden else parts[-1]
        return [part.strip() for part in parts[:-1] if part.strip()]

    def finish(self) -> list[str]:
        result = [self.buffer.strip()] if self.buffer.strip() and not self.hidden else []
        self.buffer = ""
        return result


async def finish_thread(func, *args, **kwargs):
    """La cancellazione non libera il turno mentre un'azione OS continua."""
    import asyncio

    return await finish_work(asyncio.to_thread(func, *args, **kwargs))


async def finish_work(awaitable):
    """Attende operazioni non interrompibili prima di liberare il turno."""
    import asyncio

    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise

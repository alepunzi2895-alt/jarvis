import asyncio
import logging
import time

from core import loop_watch


def test_blocked_loop_is_logged_with_stack(monkeypatch, caplog):
    monkeypatch.setattr(loop_watch, "THRESHOLD_SEC", 0.3)

    def blocking_call():
        time.sleep(1.2)

    async def main():
        loop_watch.start(asyncio.get_running_loop())
        await asyncio.sleep(0.3)
        blocking_call()
        await asyncio.sleep(0.2)

    with caplog.at_level(logging.WARNING, logger="core.loop_watch"):
        asyncio.run(main())
    assert any("Event loop fermo" in r.message and "blocking_call" in r.message for r in caplog.records)

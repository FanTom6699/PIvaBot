from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from .database import Database
from .navigation import Navigator


logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        db: Database,
        navigator: Navigator,
        interval_seconds: int = 5,
        on_tick: Callable[[], Awaitable[None]] | None = None,
    ):
        self.db = db
        self.navigator = navigator
        self.interval_seconds = interval_seconds
        self._running = False
        self.on_tick = on_tick

    async def run(self) -> None:
        self._running = True
        while self._running:
            try:
                if self.on_tick:
                    await self.on_tick()
                await self.process_due_timers()
            except Exception:
                logger.exception("Scheduler error")
            await asyncio.sleep(self.interval_seconds)

    def stop(self) -> None:
        self._running = False

    async def process_due_timers(self) -> None:
        due = await self.db.due_timers(datetime.now())
        for timer in due:
            if timer["payload"].get("type") == "milking":
                continue
            logger.info("Timer is ready: %s", timer["label"])
            await self.navigator.execute({"action": "open", "menu": timer["label"]})
            await self.db.complete_timer(timer["key"])

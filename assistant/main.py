from __future__ import annotations

import asyncio
import logging

from telethon.tl.custom import Message

from .ai import build_llm, load_json_file
from .config import AssistantConfig
from .database import Database
from .inventory import GameMemory
from .logger import setup_logging
from .navigation import Navigator
from .parser import parse_message
from .scheduler import Scheduler
from .telethon_client import GameTelegramClient


logger = logging.getLogger(__name__)


class AssistantApp:
    def __init__(self, config: AssistantConfig):
        self.config = config
        self.db = Database(config.database_path)
        self.telegram = GameTelegramClient(config)
        self.memory = GameMemory(self.db)
        self.navigator: Navigator | None = None
        self.scheduler: Scheduler | None = None
        self.llm = None
        self._message_lock = asyncio.Lock()

    async def start(self) -> None:
        await self.db.connect()
        await self.telegram.start()

        recipes, rules = await asyncio.gather(
            asyncio.to_thread(load_json_file, self.config.recipes_path),
            asyncio.to_thread(load_json_file, self.config.rules_path),
        )
        self.llm = build_llm(self.config.openai_api_key, self.config.openai_model, recipes, rules)
        self.navigator = Navigator(self.telegram, self.db, dry_run=self.config.dry_run)
        self.scheduler = Scheduler(self.db, self.navigator, self.config.loop_interval_seconds)

        self.telegram.on_target_message(self.handle_message)
        await self.telegram.open_target_dialog()

        scheduler_task = asyncio.create_task(self.scheduler.run())
        logger.info("Assistant started. dry_run=%s", self.config.dry_run)
        try:
            await self.telegram.run_until_disconnected()
        finally:
            self.scheduler.stop()
            scheduler_task.cancel()
            await self.db.close()

    async def handle_message(self, message: Message) -> None:
        async with self._message_lock:
            if not self.llm or not self.navigator:
                return
            parsed = parse_message(message)
            self.navigator.update_last_message(message, parsed)
            await self.memory.update_from_message(parsed)
            state = await self.memory.build_state(parsed)
            action = await self.llm.decide(state)
            await self.navigator.execute(action)


async def main() -> None:
    setup_logging()
    config = AssistantConfig.from_env()
    app = AssistantApp(config)
    await app.start()


if __name__ == "__main__":
    asyncio.run(main())

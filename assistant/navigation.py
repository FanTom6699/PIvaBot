from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from telethon.tl.custom import Message

from .database import Database
from .parser import ButtonInfo, ParsedMessage
from .telethon_client import GameTelegramClient


logger = logging.getLogger(__name__)


class Navigator:
    def __init__(
        self,
        telegram: GameTelegramClient,
        db: Database,
        dry_run: bool = True,
        action_delay_seconds: float = 1.5,
    ):
        self.telegram = telegram
        self.db = db
        self.dry_run = dry_run
        self.action_delay_seconds = max(0.0, action_delay_seconds)
        self._last_action_at = 0.0
        self.last_message: Message | None = None
        self.last_parsed: ParsedMessage | None = None

    def update_last_message(self, message: Message, parsed: ParsedMessage) -> None:
        self.last_message = message
        self.last_parsed = parsed

    async def execute(self, action: dict[str, Any]) -> None:
        kind = action.get("action")
        logger.info("Action: %s", action)

        if kind == "wait":
            seconds = int(action.get("seconds", 60))
            await self.db.add_action("wait", action, f"sleep {seconds}s")
            await asyncio.sleep(seconds)
            return

        if kind == "noop":
            await self.db.add_action("noop", action, "noop")
            return

        if self.dry_run:
            await self.db.add_action(kind, action, "dry_run")
            logger.info("DRY_RUN enabled, action was not sent.")
            return

        await self._wait_before_action()

        if kind == "message":
            await self.telegram.send_message(action["text"])
            await self.db.add_action("message", action, "sent")
            self._last_action_at = time.monotonic()
            return

        if kind == "open":
            await self.open_menu(action["menu"])
            await self.db.add_action("open", action, "opened")
            self._last_action_at = time.monotonic()
            return

        if kind == "click":
            await self.click_button(action["button"])
            await self.db.add_action("click", action, "clicked")
            self._last_action_at = time.monotonic()
            return

        raise ValueError(f"Unsupported action: {kind}")

    async def _wait_before_action(self) -> None:
        if self.action_delay_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_action_at
        remaining = self.action_delay_seconds - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def click_button(self, button_text: str) -> None:
        message, button = await self.find_button(button_text)
        if not message or not button:
            raise RuntimeError(f"Button not found: {button_text}")
        await message.click(button.row, button.col)

    async def open_menu(self, menu: str) -> None:
        try:
            await self.click_button(menu)
        except RuntimeError:
            await self.telegram.send_message(menu)

    async def find_button(self, button_text: str) -> tuple[Message | None, ButtonInfo | None]:
        if self.last_message and self.last_parsed:
            button = self._find_in_parsed(self.last_parsed, button_text)
            if button:
                return self.last_message, button

        for message in await self.telegram.recent_messages(limit=10):
            parsed_buttons = []
            for row_index, row in enumerate(message.buttons or []):
                for col_index, raw_button in enumerate(row):
                    text = getattr(raw_button, "text", "") or ""
                    parsed_buttons.append(ButtonInfo(text=text, row=row_index, col=col_index))
            button = self._find_button(parsed_buttons, button_text)
            if button:
                return message, button
        return None, None

    @staticmethod
    def _find_in_parsed(parsed: ParsedMessage, button_text: str) -> ButtonInfo | None:
        return Navigator._find_button(parsed.buttons, button_text)

    @staticmethod
    def _find_button(buttons: list[ButtonInfo], button_text: str) -> ButtonInfo | None:
        wanted = button_text.strip().lower()
        for button in buttons:
            if button.text.strip().lower() == wanted:
                return button
        for button in buttons:
            if wanted in button.text.strip().lower():
                return button
        return None

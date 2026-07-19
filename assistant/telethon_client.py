from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from telethon import TelegramClient, events
from telethon.tl.custom import Message

from .config import AssistantConfig


logger = logging.getLogger(__name__)
MessageHandler = Callable[[Message], Awaitable[None]]


class GameTelegramClient:
    def __init__(self, config: AssistantConfig):
        self.config = config
        self.client = TelegramClient(config.session_name, config.telegram_api_id, config.telegram_api_hash)
        self.target_entity = None

    async def start(self) -> None:
        await self.client.start(phone=self.config.telegram_phone)
        self.target_entity = await self.client.get_entity(self.config.target_bot)
        logger.info("Connected as user account. Target bot: %s", self.config.target_bot)

    async def open_target_dialog(self) -> Message:
        if not self.target_entity:
            raise RuntimeError("Client is not started")
        return await self.client.send_message(self.target_entity, "/start")

    def on_target_message(self, handler: MessageHandler) -> None:
        if not self.target_entity:
            raise RuntimeError("Target entity is not ready")

        @self.client.on(events.NewMessage(chats=self.target_entity))
        async def _wrapped(event):
            await handler(event.message)

        @self.client.on(events.MessageEdited(chats=self.target_entity))
        async def _edited(event):
            await handler(event.message)

    async def recent_messages(self, limit: int) -> list[Message]:
        if not self.target_entity:
            raise RuntimeError("Client is not started")
        return [message async for message in self.client.iter_messages(self.target_entity, limit=limit)]

    async def send_message(self, text: str) -> Message:
        if not self.target_entity:
            raise RuntimeError("Client is not started")
        return await self.client.send_message(self.target_entity, text)

    async def run_until_disconnected(self) -> None:
        await self.client.run_until_disconnected()


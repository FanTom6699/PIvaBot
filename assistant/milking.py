from __future__ import annotations

import logging
from datetime import datetime, timedelta

from telethon.tl.custom import Message

from .database import Database
from .navigation import Navigator
from .parser import ButtonInfo, ParsedMessage


logger = logging.getLogger(__name__)


class MilkingController:
    """Reliable feeding and milking loop for the target game bot."""

    COOLDOWN_KEY = "milking:cooldown"
    COOLDOWN_SECONDS = 12 * 60

    def __init__(self, navigator: Navigator, db: Database, enabled: bool = True):
        self.navigator = navigator
        self.db = db
        self.enabled = enabled
        self.phase = "idle"

    async def start(self) -> None:
        if not self.enabled:
            return
        existing = await self.db.get_timer(self.COOLDOWN_KEY)
        if existing:
            self.phase = "cooldown"
            logger.info("Milking cooldown restored until %s", existing["ready_at"])
            return
        self.phase = "await_main"
        await self._send_command("\u043c\u0443\u043a")
        logger.info("Milking flow started with command: мук")

    async def handle_message(self, message: Message, parsed: ParsedMessage) -> bool:
        del message
        if not self.enabled or self.phase in {"idle", "cooldown"}:
            return False

        buttons = parsed.buttons
        if self.phase == "await_main":
            if parsed.food_percent is None:
                return True
            if parsed.food_percent < 99:
                self.phase = "food_menu"
                await self._click_food_menu(buttons)
            else:
                self.phase = "milk_plus"
                await self._click_milk_plus(buttons)
            return True

        if self.phase == "food_menu":
            grass = self._find_grass(buttons)
            if grass:
                self.phase = "after_grass"
                await self.navigator.execute({"action": "click", "button": grass.text})
            return True

        if self.phase == "after_grass":
            back = self._find_back(buttons)
            if back:
                self.phase = "await_main"
                await self.navigator.execute({"action": "click", "button": back.text})
            return True

        if self.phase == "milk_plus":
            button = self._find_milk_plus(buttons)
            if button:
                self.phase = "milk_button"
                await self.navigator.execute({"action": "click", "button": button.text})
                return True
            button = self._find_milk_button(buttons)
            if button:
                self.phase = "milking_result"
                await self.navigator.execute({"action": "click", "button": button.text})
                return True
            logger.warning("Milk+ or milk button was not found. Buttons: %s", self._button_labels(buttons))
            return True

        if self.phase == "milk_button":
            button = self._find_milk_button(buttons)
            if button:
                self.phase = "milking_result"
                await self.navigator.execute({"action": "click", "button": button.text})
            else:
                logger.warning("Milk button was not found. Buttons: %s", self._button_labels(buttons))
            return True

        if self.phase == "milking_result":
            if self._looks_like_milking_success(parsed.text):
                await self._save_cooldown()
                self.phase = "cooldown"
                logger.info("Milking succeeded; next attempt in 12 minutes")
            return True

        return True

    async def tick(self) -> None:
        if not self.enabled or self.phase != "cooldown":
            return
        for timer in await self.db.due_timers(datetime.now()):
            if timer["key"] != self.COOLDOWN_KEY:
                continue
            await self.db.complete_timer(self.COOLDOWN_KEY)
            self.phase = "await_main"
            await self._send_command("\u043c\u0443\u043a")
            logger.info("Milking cooldown finished; checking food again")
            break

    async def _save_cooldown(self) -> None:
        ready_at = datetime.now() + timedelta(seconds=self.COOLDOWN_SECONDS)
        await self.db.upsert_timer(
            self.COOLDOWN_KEY,
            "\u0414\u043e\u0439\u043a\u0430 \u0447\u0435\u0440\u0435\u0437 12 \u043c\u0438\u043d\u0443\u0442",
            ready_at.isoformat(timespec="seconds"),
            {"type": "milking", "seconds": self.COOLDOWN_SECONDS},
        )

    async def _send_command(self, text: str) -> None:
        await self.navigator.execute({"action": "message", "text": text})

    async def _click_food_menu(self, buttons: list[ButtonInfo]) -> None:
        button = self._find_food_menu(buttons)
        if button:
            await self.navigator.execute({"action": "click", "button": button.text})
        else:
            logger.warning("Food menu button was not found; waiting for a fresh message")

    async def _click_milk_plus(self, buttons: list[ButtonInfo]) -> None:
        button = self._find_milk_plus(buttons)
        if button:
            await self.navigator.execute({"action": "click", "button": button.text})
        else:
            logger.warning("Milk+ button was not found; waiting for a fresh message")

    @staticmethod
    def _find_food_menu(buttons: list[ButtonInfo]) -> ButtonInfo | None:
        semantic = ("\u0435\u0434\u0430", "\u043a\u043e\u0440\u043c", "\u043f\u0438\u0442", "\u0445\u0430\u0432\u0447\u0438\u043a")
        for button in buttons:
            if any(word in button.text.casefold() for word in semantic):
                return button

        # Some versions show only an emoji. Use the first non-navigation,
        # non-milking button in the menu's visual order.
        excluded = ("\u043d\u0430\u0437\u0430\u0434", "\u0434\u043e\u0438\u0442\u044c", "\u043f\u043e\u0434\u043e\u0438\u0442\u044c", "\u043c\u043e\u043b\u043e\u043a\u043e")
        for button in sorted(buttons, key=lambda item: (item.row, item.col)):
            if not any(word in button.text.casefold() for word in excluded):
                return button
        return None

    @staticmethod
    def _find_grass(buttons: list[ButtonInfo]) -> ButtonInfo | None:
        for button in buttons:
            label = button.text.casefold()
            if "\u0442\u0440\u0430\u0432" in label or "+5" in label or "5%" in label:
                return button

        excluded = ("\u043d\u0430\u0437\u0430\u0434", "\u0441\u0443\u043f", "\u0431\u0440\u043e\u043a", "\u0448\u0435\u0439\u043a", "\u043c\u043e\u043b\u043e\u043a\u043e")
        for button in sorted(buttons, key=lambda item: (item.row, item.col)):
            if not any(word in button.text.casefold() for word in excluded):
                return button
        return None

    @staticmethod
    def _find_milk_plus(buttons: list[ButtonInfo]) -> ButtonInfo | None:
        for button in buttons:
            label = button.text.casefold()
            if MilkingController._is_milk_button_label(label):
                continue
            if (
                "\u043c\u043e\u043b\u043e\u043a\u043e+" in label
                or "x2" in label
                or "\u00d72" in label
                or "\U0001f9fc" in label
            ):
                return button
        return None

    @staticmethod
    def _find_milk_button(buttons: list[ButtonInfo]) -> ButtonInfo | None:
        for button in buttons:
            label = button.text.casefold()
            if MilkingController._is_milk_button_label(label):
                return button
        return None

    @staticmethod
    def _is_milk_button_label(label: str) -> bool:
        normalized = label.strip()
        return "\u043f\u043e\u0434\u043e\u0438\u0442\u044c" in normalized or "\u0434\u043e\u0438\u0442\u044c" in normalized

    @staticmethod
    def _find_back(buttons: list[ButtonInfo]) -> ButtonInfo | None:
        for button in buttons:
            if "\u043d\u0430\u0437\u0430\u0434" in button.text.casefold():
                return button
        return None

    @staticmethod
    def _looks_like_milking_success(text: str) -> bool:
        lower = text.casefold()
        failure_words = ("\u043d\u0435\u043b\u044c\u0437\u044f", "\u043e\u0448\u0438\u0431", "\u043d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c", "\u043d\u0435\u0434\u043e\u0441\u0442\u0430\u0442")
        if any(word in lower for word in failure_words):
            return False
        return "\u043c\u043e\u043b\u043e\u043a" in lower and any(
            word in lower for word in ("\u043f\u043e\u043b\u0443\u0447", "\u0443\u0441\u043f\u0435\u0448", "+", "x2", "\u00d72")
        )

    @staticmethod
    def _button_labels(buttons: list[ButtonInfo]) -> list[str]:
        return [button.text for button in buttons]

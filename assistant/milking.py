from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
import time

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
        self._last_menu_refresh_at = 0.0

    async def start(self) -> None:
        if not self.enabled:
            return
        existing = await self.db.get_timer(self.COOLDOWN_KEY)
        if existing:
            logger.info("Stored milking cooldown exists until %s; checking real game menu", existing["ready_at"])
        self.phase = "await_main"
        await self._send_command("\u043c\u0443\u043a")
        logger.info("Milking flow started with command: мук")

    async def handle_message(self, message: Message, parsed: ParsedMessage) -> bool:
        del message
        if not self.enabled or self.phase == "idle":
            return False

        logger.info(
            "Milking phase=%s food=%s cooldown=%s buttons=%s",
            self.phase,
            parsed.food_percent,
            parsed.milking_cooldown_seconds,
            self._button_labels(parsed.buttons),
        )

        if parsed.milking_cooldown_seconds:
            await self._save_cooldown(parsed.milking_cooldown_seconds)
            self.phase = "cooldown"
            logger.info("Milking cooldown detected from message: %s seconds", parsed.milking_cooldown_seconds)
            return True

        if self.phase == "cooldown":
            return True

        buttons = parsed.buttons
        cleanup = self._find_cleanup_button(buttons)
        if cleanup:
            phase_before_cleanup = self.phase
            await self.navigator.click_current_button(cleanup)
            if phase_before_cleanup == "milking_result":
                await self._save_cooldown(self.COOLDOWN_SECONDS)
                self.phase = "cooldown"
                logger.info("Cleanup after milking clicked; next attempt in 12 minutes")
            else:
                self.phase = "await_main"
            return True

        if self.phase == "await_main":
            milk_button = self._find_milk_button(buttons)
            if not milk_button:
                cooldown_seconds = self._cooldown_seconds_from_buttons(buttons)
                if cooldown_seconds:
                    await self._save_cooldown(cooldown_seconds)
                    self.phase = "cooldown"
                    logger.info("Milking cooldown detected from button: %s seconds", cooldown_seconds)
                    return True

            if parsed.food_percent is None:
                await self._refresh_main_menu("Food percent was not found")
                return True
            if parsed.food_percent < 99:
                if await self._click_food_menu(buttons):
                    self.phase = "food_menu"
            else:
                self.phase = "milk_plus"
                await self._click_milk_plus(buttons)
            return True

        if self.phase == "food_menu":
            grass = self._find_grass(buttons)
            if grass:
                self.phase = "after_grass"
                await self.navigator.click_current_button(grass)
            elif parsed.food_percent is not None:
                self.phase = "await_main"
                await self._click_food_menu(buttons)
            else:
                logger.warning("Grass button was not found. Buttons: %s", self._button_labels(buttons))
            return True

        if self.phase == "after_grass":
            back = self._find_back(buttons)
            if back:
                await self.navigator.click_current_button(back)
                self.phase = "await_main"
                await self._send_command("\u043c\u0443\u043a")
            else:
                logger.warning("Back button was not found. Buttons: %s", self._button_labels(buttons))
            return True

        if self.phase == "milk_plus":
            button = self._find_milk_plus(buttons)
            if button:
                self.phase = "milk_button"
                await self.navigator.click_current_button(button)
                return True
            button = self._find_milk_button(buttons)
            if button:
                self.phase = "milking_result"
                await self.navigator.click_current_button(button)
                return True
            logger.warning("Milk+ or milk button was not found. Buttons: %s", self._button_labels(buttons))
            return True

        if self.phase == "milk_button":
            button = self._find_milk_button(buttons)
            if button:
                self.phase = "milking_result"
                await self.navigator.click_current_button(button)
            else:
                logger.warning("Milk button was not found. Buttons: %s", self._button_labels(buttons))
            return True

        if self.phase == "milking_result":
            if self._looks_like_milking_success(parsed.text):
                await self._save_cooldown(parsed.milking_cooldown_seconds or self.COOLDOWN_SECONDS)
                self.phase = "cooldown"
                logger.info("Milking succeeded; next attempt is scheduled")
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
            self._last_menu_refresh_at = time.monotonic()
            logger.info("Milking cooldown finished; checking food again")
            break

    async def _save_cooldown(self, seconds: int) -> None:
        ready_at = datetime.now() + timedelta(seconds=seconds)
        await self.db.upsert_timer(
            self.COOLDOWN_KEY,
            "\u0414\u043e\u0439\u043a\u0430 \u0447\u0435\u0440\u0435\u0437 \u0442\u0430\u0439\u043c\u0435\u0440 \u0438\u0437 \u0438\u0433\u0440\u044b",
            ready_at.isoformat(timespec="seconds"),
            {"type": "milking", "seconds": seconds},
        )

    async def _send_command(self, text: str) -> None:
        await self.navigator.execute({"action": "message", "text": text})

    async def _refresh_main_menu(self, reason: str) -> None:
        now = time.monotonic()
        if now - self._last_menu_refresh_at < 8:
            logger.info("%s; waiting for menu update", reason)
            return
        logger.info("%s; refreshing main menu", reason)
        self._last_menu_refresh_at = now
        await self._send_command("\u043c\u0443\u043a")

    async def _click_food_menu(self, buttons: list[ButtonInfo]) -> bool:
        button = self._find_food_menu(buttons)
        if button:
            await self.navigator.click_current_button(button)
            return True
        logger.warning("Food menu button was not found. Buttons: %s", self._button_labels(buttons))
        return False

    async def _click_milk_plus(self, buttons: list[ButtonInfo]) -> None:
        button = self._find_milk_plus(buttons)
        if button:
            await self.navigator.click_current_button(button)
        else:
            logger.warning("Milk+ button was not found; waiting for a fresh message")

    @staticmethod
    def _find_food_menu(buttons: list[ButtonInfo]) -> ButtonInfo | None:
        semantic = ("\u0435\u0434\u0430", "\u043a\u043e\u0440\u043c", "\u043f\u0438\u0442", "\u0445\u0430\u0432\u0447\u0438\u043a")
        for button in buttons:
            if any(word in button.text.casefold() for word in semantic):
                return button

        sorted_buttons = sorted(buttons, key=lambda item: (item.row, item.col))
        if len(sorted_buttons) >= 2:
            candidate = sorted_buttons[1]
            label = candidate.text.casefold()
            if (
                not MilkingController._is_timer_label(label)
                and not MilkingController._is_milk_button_label(label)
                and not MilkingController._is_utility_label(candidate.text)
            ):
                return candidate

        # Main menu shows a single food emoji between timer/milk and utility buttons.
        excluded = (
            "\u043d\u0430\u0437\u0430\u0434",
            "\u0441\u043b\u0438\u0432",
            "\u0440\u044e\u043a\u0437\u0430\u043a",
            "\u0434\u043e\u0438\u0442\u044c",
            "\u043f\u043e\u0434\u043e\u0438\u0442\u044c",
            "\u043c\u043e\u043b\u043e\u043a\u043e",
            "\u0443\u0431\u0440\u0430\u0442\u044c",
        )
        excluded_icons = ("\U0001f392", "\U0001f95b", "\U0001f9fc", "\U0001f4a9", "\u23f0")
        for button in sorted(buttons, key=lambda item: (item.row, item.col)):
            label = button.text.casefold()
            if MilkingController._is_timer_label(label):
                continue
            if any(word in label for word in excluded):
                continue
            if any(icon in button.text for icon in excluded_icons):
                continue
            if len(button.text.strip()) <= 4:
                return button
        return None

    @staticmethod
    def _find_grass(buttons: list[ButtonInfo]) -> ButtonInfo | None:
        for button in buttons:
            label = button.text.casefold()
            if "\U0001f33f" in button.text or "\u0442\u0440\u0430\u0432" in label or "+5" in label or "5%" in label:
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
    def _find_cleanup_button(buttons: list[ButtonInfo]) -> ButtonInfo | None:
        for button in buttons:
            label = button.text.casefold()
            if "\u0443\u0431\u0440\u0430\u0442\u044c" in label:
                return button
        return None

    @staticmethod
    def _is_milk_button_label(label: str) -> bool:
        normalized = label.strip()
        return "\u043f\u043e\u0434\u043e\u0438\u0442\u044c" in normalized or "\u0434\u043e\u0438\u0442\u044c" in normalized

    @staticmethod
    def _is_timer_label(label: str) -> bool:
        has_digit = any(char.isdigit() for char in label)
        timer_words = (
            "\u043c\u0438\u043d",
            "\u043c\u0438\u043d\u0443\u0442",
            "\u0441\u0435\u043a",
            "\u0447\u0430\u0441",
            "\u043a\u0434",
            "\u0442\u0430\u0439\u043c\u0435\u0440",
        )
        return has_digit and any(word in label for word in timer_words)

    @staticmethod
    def _is_utility_label(label: str) -> bool:
        lower = label.casefold()
        utility_words = (
            "\u043d\u0430\u0437\u0430\u0434",
            "\u0441\u043b\u0438\u0432",
            "\u0440\u044e\u043a\u0437\u0430\u043a",
            "\u0443\u0431\u0440\u0430\u0442\u044c",
        )
        utility_icons = ("\U0001f392", "\U0001f4a9", "\u23f0")
        return any(word in lower for word in utility_words) or any(icon in label for icon in utility_icons)

    @staticmethod
    def _cooldown_seconds_from_buttons(buttons: list[ButtonInfo]) -> int | None:
        for button in buttons:
            label = button.text.casefold()
            if not MilkingController._is_timer_label(label):
                continue
            seconds = MilkingController._duration_seconds(label)
            if seconds:
                return seconds
        return None

    @staticmethod
    def _duration_seconds(text: str) -> int | None:
        colon_match = re.search(r"(?<!\d)(?P<minutes>\d{1,2})\s*:\s*(?P<seconds>\d{2})(?!\d)", text)
        if colon_match:
            return int(colon_match.group("minutes")) * 60 + int(colon_match.group("seconds"))

        hours = MilkingController._first_duration_part(
            r"(\d+)\s*(?:\u0447|\u0447\u0430\u0441|\u0447\u0430\u0441\u0430|\u0447\u0430\u0441\u043e\u0432|h)\b",
            text,
        )
        minutes = MilkingController._first_duration_part(
            r"(\d+)\s*(?:\u043c|\u043c\u0438\u043d|\u043c\u0438\u043d\u0443\u0442|\u043c\u0438\u043d\u0443\u0442\u044b|minutes|m)\b",
            text,
        )
        seconds = MilkingController._first_duration_part(
            r"(\d+)\s*(?:\u0441|\u0441\u0435\u043a|\u0441\u0435\u043a\u0443\u043d\u0434|\u0441\u0435\u043a\u0443\u043d\u0434\u044b|seconds|s)\b",
            text,
        )
        total = hours * 3600 + minutes * 60 + seconds
        return total if total > 0 else None

    @staticmethod
    def _first_duration_part(pattern: str, text: str) -> int:
        match = re.search(pattern, text, re.IGNORECASE)
        return int(match.group(1)) if match else 0

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

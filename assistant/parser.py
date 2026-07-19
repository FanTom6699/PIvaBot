from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass(slots=True)
class ButtonInfo:
    text: str
    row: int
    col: int


@dataclass(slots=True)
class ParsedMessage:
    message_id: int
    text: str
    buttons: list[ButtonInfo] = field(default_factory=list)
    resources: dict[str, int] = field(default_factory=dict)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    animals: list[dict[str, Any]] = field(default_factory=list)
    timers: list[dict[str, Any]] = field(default_factory=list)
    account: dict[str, Any] = field(default_factory=dict)
    food_percent: int | None = None
    milking_cooldown_seconds: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


RESOURCE_ALIASES = {
    "🌾": "wheat",
    "🥚": "egg",
    "🥛": "milk",
    "🐔": "chicken",
    "🐮": "cow",
    "🍺": "beer",
    "💰": "coins",
    "⭐": "xp",
}

RESOURCE_NAME_RE = re.compile(
    r"(?P<name>[🌾🥚🥛🐔🐮🍺💰⭐][^\n:：xх×]{0,32}?)[\s:：]*(?:x|х|×)?\s*(?P<amount>-?\d[\d\s]*)",
    re.IGNORECASE,
)
LEVEL_RE = re.compile(r"(?:уровень|ур\.|level)\D*(?P<level>\d+)", re.IGNORECASE)
HOURS_RE = re.compile(r"(\d+)\s*(?:ч|час|часа|часов|h)\b", re.IGNORECASE)
MINUTES_RE = re.compile(r"(\d+)\s*(?:м|мин|минут|minutes|m)\b", re.IGNORECASE)
SECONDS_RE = re.compile(r"(\d+)\s*(?:с|сек|секунд|seconds|s)\b", re.IGNORECASE)
ANIMAL_RE = re.compile(r"(курица|корова|коза|овца|свинья|пчела|животн)", re.IGNORECASE)
TASK_RE = re.compile(r"(задани|заказ|квест|мисси)", re.IGNORECASE)


def normalize_resource_name(name: str) -> str:
    clean = " ".join(name.strip().split())
    first = clean[:1]
    if first in RESOURCE_ALIASES:
        return RESOURCE_ALIASES[first]
    return clean.lower()


def parse_buttons(message: Any) -> list[ButtonInfo]:
    buttons: list[ButtonInfo] = []
    for row_index, row in enumerate(message.buttons or []):
        for col_index, button in enumerate(row):
            text = getattr(button, "text", "") or ""
            if text:
                buttons.append(ButtonInfo(text=text, row=row_index, col=col_index))
    return buttons


def parse_resources(text: str) -> dict[str, int]:
    resources: dict[str, int] = {}
    for match in RESOURCE_NAME_RE.finditer(text):
        name = normalize_resource_name(match.group("name"))
        amount = int(match.group("amount").replace(" ", ""))
        resources[name] = resources.get(name, 0) + amount
    return resources


def parse_timers(text: str, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now()
    timers: list[dict[str, Any]] = []
    for line in text.splitlines():
        lower = line.lower()
        if not any(marker in lower for marker in ("через", "готов", "осталось", "до ", "таймер")):
            continue

        hours = _first_int(HOURS_RE, line)
        minutes = _first_int(MINUTES_RE, line)
        seconds = _first_int(SECONDS_RE, line)
        total = hours * 3600 + minutes * 60 + seconds
        if total <= 0:
            continue

        timers.append(
            {
                "label": line.strip(),
                "seconds": total,
                "ready_at": (now + timedelta(seconds=total)).isoformat(timespec="seconds"),
            }
        )
    return timers


def _first_int(pattern: re.Pattern[str], text: str) -> int:
    match = pattern.search(text)
    return int(match.group(1)) if match else 0


def parse_account(text: str) -> dict[str, Any]:
    account: dict[str, Any] = {}
    level = LEVEL_RE.search(text)
    if level:
        account["level"] = int(level.group("level"))
    return account


def parse_food_percent(text: str) -> int | None:
    pattern = (
        r"(?:\u0445\u0430\u0432\u0447\u0438\u043a|\u0441\u044b\u0442\u043e\u0441\u0442\u044c|"
        r"\u0435\u0434\u0430|food)[^\d]{0,24}(?P<percent>\d{1,3})\s*%?"
    )
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    return min(100, int(match.group("percent")))


def parse_milking_cooldown_seconds(text: str) -> int | None:
    lower = text.casefold()
    if "\u0434\u043e\u0438\u0442" not in lower and "\u0434\u043e\u0439\u043a" not in lower and "\u043c\u043e\u043b\u043e\u043a" not in lower:
        return None

    timer_words = (
        "\u0447\u0435\u0440\u0435\u0437",
        "\u0434\u043e ",
        "\u043e\u0441\u0442\u0430\u043b",
        "\u0436\u0434\u0430\u0442\u044c",
        "\u043a\u0434",
        "\u0442\u0430\u0439\u043c\u0435\u0440",
    )
    if not any(word in lower for word in timer_words):
        return None

    colon_match = re.search(r"(?<!\d)(?P<minutes>\d{1,2})\s*:\s*(?P<seconds>\d{2})(?!\d)", lower)
    if colon_match:
        return int(colon_match.group("minutes")) * 60 + int(colon_match.group("seconds"))

    hours = _first_int(
        re.compile(r"(\d+)\s*(?:\u0447|\u0447\u0430\u0441|\u0447\u0430\u0441\u0430|\u0447\u0430\u0441\u043e\u0432|h)\b", re.IGNORECASE),
        lower,
    )
    minutes = _first_int(
        re.compile(r"(\d+)\s*(?:\u043c|\u043c\u0438\u043d|\u043c\u0438\u043d\u0443\u0442|minutes|m)\b", re.IGNORECASE),
        lower,
    )
    seconds = _first_int(
        re.compile(r"(\d+)\s*(?:\u0441|\u0441\u0435\u043a|\u0441\u0435\u043a\u0443\u043d\u0434|seconds|s)\b", re.IGNORECASE),
        lower,
    )
    total = hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else None


def parse_tasks(text: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for line in text.splitlines():
        if TASK_RE.search(line):
            tasks.append({"text": line.strip(), "status": "unknown"})
    return tasks


def parse_animals(text: str) -> list[dict[str, Any]]:
    animals: list[dict[str, Any]] = []
    for line in text.splitlines():
        if ANIMAL_RE.search(line):
            animals.append({"text": line.strip(), "status": "unknown"})
    return animals


def parse_message(message: Any) -> ParsedMessage:
    text = message.raw_text or ""
    return ParsedMessage(
        message_id=message.id,
        text=text,
        buttons=parse_buttons(message),
        resources=parse_resources(text),
        tasks=parse_tasks(text),
        animals=parse_animals(text),
        timers=parse_timers(text),
        account=parse_account(text),
        food_percent=parse_food_percent(text),
        milking_cooldown_seconds=parse_milking_cooldown_seconds(text),
        raw={"date": message.date.isoformat() if message.date else None},
    )

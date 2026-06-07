import re

from aiogram.filters import Filter
from aiogram.types import Message


def normalize_alias_text(text: str | None) -> str:
    if not text:
        return ""

    normalized = text.strip().casefold().replace("ё", "е")
    normalized = re.sub(r"[!?.;,]+$", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


class GroupTextAlias(Filter):
    def __init__(self, *aliases: str):
        self.aliases = {normalize_alias_text(alias) for alias in aliases}

    async def __call__(self, message: Message) -> bool:
        if message.chat.type == "private" or not message.text:
            return False

        text = normalize_alias_text(message.text)
        return bool(text and not text.startswith("/") and text in self.aliases)


BEER_ALIASES = (
    "пиво",
    "выпить пиво",
    "попить пиво",
    "налить пиво",
    "налей пиво",
    "бахнуть пиво",
    "пивка",
    "пивко",
    "beer",
)

FARM_ALIASES = (
    "ферма",
    "открыть ферму",
    "моя ферма",
    "поле",
    "огород",
    "farm",
)

PROFILE_ALIASES = (
    "профиль",
    "мой профиль",
    "ми",
    "me",
)

CHAT_TOP_ALIASES = (
    "топ",
    "топ чата",
    "топ пива",
    "рейтинг чата",
)

GLOBAL_RATING_ALIASES = (
    "рейтинг",
    "рейт глоб",
    "общий рейтинг",
    "глобальный рейтинг",
    "рейтинг глобальный",
)

BEER_RATING_ALIASES = (
    "рейтинг пиво",
    "рейтинг пива",
    "рейт пиво",
    "топ рейтинг пиво",
)

GRAIN_RATING_ALIASES = (
    "рейтинг зерно",
    "рейтинг зерна",
    "рейт зерно",
)

HOPS_RATING_ALIASES = (
    "рейтинг хмель",
    "рейтинг хмеля",
    "рейт хмель",
)

JACKPOT_ALIASES = (
    "джекпот",
    "банк удачи",
    "банк пива",
)

HELP_ALIASES = (
    "помощь",
    "команды",
    "хелп",
    "help",
)

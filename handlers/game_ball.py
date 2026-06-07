import asyncio
import re
from decimal import Decimal, ROUND_HALF_UP

from aiogram import Bot, Router
from aiogram.filters import Filter
from aiogram.types import Message

from database import Database
from .common import check_user_registered
from utils import mention_user

ball_router = Router()

BALL_MIN_BET = 10
BALL_MAX_BET = 1000
BALL_MULTIPLIER = Decimal("1.2")
BALL_HIT_VALUES = {4, 5}


class BallBetFilter(Filter):
    async def __call__(self, message: Message) -> bool | dict:
        if message.chat.type == "private" or not message.text:
            return False

        text = message.text.strip().casefold().replace("ё", "е")
        match = re.fullmatch(r"мяч\s+(\d+)", text)
        if not match:
            return False

        return {"stake": int(match.group(1))}


def get_ball_win(stake: int) -> int:
    return int((Decimal(stake) * BALL_MULTIPLIER).to_integral_value(rounding=ROUND_HALF_UP))


@ball_router.message(BallBetFilter())
async def cmd_ball(message: Message, bot: Bot, db: Database, stake: int):
    if not await check_user_registered(message, bot, db):
        return

    user = message.from_user
    balance = await db.get_user_beer_rating(user.id)

    if not (BALL_MIN_BET <= stake <= BALL_MAX_BET):
        await message.reply(
            (
                "🏀 <b>Пивной бросок</b>\n\n"
                f"Ставка должна быть от <b>{BALL_MIN_BET}</b> до <b>{BALL_MAX_BET}</b> 🍺.\n"
                f"Пример: <code>мяч {BALL_MIN_BET}</code>"
            ),
            parse_mode="HTML",
        )
        return

    if balance < stake:
        await message.reply(
            (
                "🏀 <b>Пивной бросок</b>\n\n"
                "Не хватает 🍺 на ставку.\n"
                f"Нужно: <b>{stake}</b> 🍺\n"
                f"У тебя: <b>{balance}</b> 🍺"
            ),
            parse_mode="HTML",
        )
        return

    await db.change_rating(user.id, -stake)
    try:
        dice_message = await bot.send_dice(
            chat_id=message.chat.id,
            emoji="🏀",
        )
    except Exception:
        await db.change_rating(user.id, stake)
        await message.reply(
            "🏀 Не получилось бросить мяч. Ставка возвращена.",
            parse_mode="HTML",
        )
        return

    await asyncio.sleep(4)

    dice_value = dice_message.dice.value if dice_message.dice else 0
    player = mention_user(user.id, user.full_name)

    if dice_value in BALL_HIT_VALUES:
        prize = get_ball_win(stake)
        profit = prize - stake
        await db.change_rating(user.id, prize)
        text = (
            "🏀 <b>Попал в кольцо!</b>\n\n"
            f"{player} забирает <b>{prize}</b> 🍺\n"
            f"Чистый плюс: <b>+{profit}</b> 🍺\n\n"
            "<code>--- --- ---</code>\n"
            f"Множитель: <b>x{BALL_MULTIPLIER}</b>"
        )
    else:
        text = (
            "🏀 <b>Мимо кольца</b>\n\n"
            f"{player} теряет ставку <b>{stake}</b> 🍺\n\n"
            "<code>--- --- ---</code>\n"
            "Попробовать ещё: <code>мяч 10</code>"
        )

    await dice_message.reply(text, parse_mode="HTML")

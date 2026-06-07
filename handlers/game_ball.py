import asyncio
import re
from decimal import Decimal, ROUND_HALF_UP

from aiogram import Bot, Router
from aiogram.filters import Command, Filter
from aiogram.types import Message

from database import Database
from .common import check_user_registered
from utils import mention_user

ball_router = Router()

BALL_MIN_BET = 10
BALL_MAX_BET = 1000
BALL_MULTIPLIER = Decimal("1.2")
BALL_HIT_VALUES = {4, 5}

BALL_EMOJI = "\U0001f3c0"
BEER_EMOJI = "\U0001f37a"
BALL_WORD = "\u043c\u044f\u0447"


def parse_ball_stake(text: str | None) -> int | None:
    if not text:
        return None

    normalized = text.strip().casefold().replace("\u0451", "\u0435")
    patterns = (
        rf"^{BALL_WORD}\s+(\d+)$",
        rf"^{BALL_EMOJI}\s+(\d+)$",
        r"^/ball(?:@\w+)?\s+(\d+)$",
    )

    for pattern in patterns:
        match = re.fullmatch(pattern, normalized)
        if match:
            return int(match.group(1))

    return None


class BallBetFilter(Filter):
    async def __call__(self, message: Message) -> bool | dict:
        stake = parse_ball_stake(message.text)
        if stake is None:
            return False

        return {"stake": stake}


def get_ball_win(stake: int) -> int:
    return int((Decimal(stake) * BALL_MULTIPLIER).to_integral_value(rounding=ROUND_HALF_UP))


def ball_example() -> str:
    return f"<code>{BALL_WORD} {BALL_MIN_BET}</code>"


@ball_router.message(Command("ball"))
async def cmd_ball_command(message: Message, bot: Bot, db: Database):
    stake = parse_ball_stake(message.text)
    if stake is None:
        await message.answer(
            (
                f"{BALL_EMOJI} <b>\u041f\u0438\u0432\u043d\u043e\u0439 \u0431\u0440\u043e\u0441\u043e\u043a</b>\n\n"
                f"\u041d\u0430\u043f\u0438\u0448\u0438: {ball_example()}"
            ),
            parse_mode="HTML",
        )
        return

    await play_ball(message, bot, db, stake)


@ball_router.message(BallBetFilter())
async def cmd_ball_text(message: Message, bot: Bot, db: Database, stake: int):
    await play_ball(message, bot, db, stake)


async def play_ball(message: Message, bot: Bot, db: Database, stake: int):
    user = message.from_user
    if message.chat.type == "private":
        await db.add_user(user.id, user.first_name, user.last_name, user.username)
    elif not await check_user_registered(message, bot, db):
        return

    balance = await db.get_user_beer_rating(user.id)

    if not (BALL_MIN_BET <= stake <= BALL_MAX_BET):
        await message.reply(
            (
                f"{BALL_EMOJI} <b>\u041f\u0438\u0432\u043d\u043e\u0439 \u0431\u0440\u043e\u0441\u043e\u043a</b>\n\n"
                f"\u0421\u0442\u0430\u0432\u043a\u0430 \u0434\u043e\u043b\u0436\u043d\u0430 \u0431\u044b\u0442\u044c \u043e\u0442 <b>{BALL_MIN_BET}</b> "
                f"\u0434\u043e <b>{BALL_MAX_BET}</b> {BEER_EMOJI}.\n"
                f"\u041f\u0440\u0438\u043c\u0435\u0440: {ball_example()}"
            ),
            parse_mode="HTML",
        )
        return

    if balance < stake:
        await message.reply(
            (
                f"{BALL_EMOJI} <b>\u041f\u0438\u0432\u043d\u043e\u0439 \u0431\u0440\u043e\u0441\u043e\u043a</b>\n\n"
                f"\u041d\u0435 \u0445\u0432\u0430\u0442\u0430\u0435\u0442 {BEER_EMOJI} \u043d\u0430 \u0441\u0442\u0430\u0432\u043a\u0443.\n"
                f"\u041d\u0443\u0436\u043d\u043e: <b>{stake}</b> {BEER_EMOJI}\n"
                f"\u0423 \u0442\u0435\u0431\u044f: <b>{balance}</b> {BEER_EMOJI}"
            ),
            parse_mode="HTML",
        )
        return

    await db.change_rating(user.id, -stake)
    try:
        dice_message = await bot.send_dice(
            chat_id=message.chat.id,
            emoji=BALL_EMOJI,
        )
    except Exception:
        await db.change_rating(user.id, stake)
        await message.reply(
            f"{BALL_EMOJI} \u041d\u0435 \u043f\u043e\u043b\u0443\u0447\u0438\u043b\u043e\u0441\u044c \u0431\u0440\u043e\u0441\u0438\u0442\u044c \u043c\u044f\u0447. "
            "\u0421\u0442\u0430\u0432\u043a\u0430 \u0432\u043e\u0437\u0432\u0440\u0430\u0449\u0435\u043d\u0430.",
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
            f"{BALL_EMOJI} <b>\u041f\u043e\u043f\u0430\u043b \u0432 \u043a\u043e\u043b\u044c\u0446\u043e!</b>\n\n"
            f"{player} \u0437\u0430\u0431\u0438\u0440\u0430\u0435\u0442 <b>{prize}</b> {BEER_EMOJI}\n"
            f"\u0427\u0438\u0441\u0442\u044b\u0439 \u043f\u043b\u044e\u0441: <b>+{profit}</b> {BEER_EMOJI}\n\n"
            "<code>--- --- ---</code>\n"
            f"\u041c\u043d\u043e\u0436\u0438\u0442\u0435\u043b\u044c: <b>x{BALL_MULTIPLIER}</b>"
        )
    else:
        text = (
            f"{BALL_EMOJI} <b>\u041c\u0438\u043c\u043e \u043a\u043e\u043b\u044c\u0446\u0430</b>\n\n"
            f"{player} \u0442\u0435\u0440\u044f\u0435\u0442 \u0441\u0442\u0430\u0432\u043a\u0443 <b>{stake}</b> {BEER_EMOJI}\n\n"
            "<code>--- --- ---</code>\n"
            f"\u041f\u043e\u043f\u0440\u043e\u0431\u043e\u0432\u0430\u0442\u044c \u0435\u0449\u0435: {ball_example()}"
        )

    await dice_message.reply(text, parse_mode="HTML")

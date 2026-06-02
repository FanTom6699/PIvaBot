import random
from datetime import datetime, timedelta
from typing import Any

from database import Database
from settings import SettingsManager
from utils import format_time_delta

user_spam_tracker = {}
DIVIDER = "<code>--- --- ---</code>"

BEER_WIN_LINES = [
    "Бармен молча кивнул. Похоже, ты сегодня свой.",
    "Пена легла идеально. Такое бывает не просто так.",
    "Кружка зашла мягко, как победа без объяснений.",
    "Кто-то сказал: «ну он умеет». И был прав.",
    "Ты сделал глоток, и бар стал чуть уважительнее.",
    "Сегодня удача сидит рядом и просит добавки.",
    "Бармен налил с таким видом, будто это инвестиция.",
    "Первый глоток решил все за тебя.",
    "Кружка звякнула уверенно. Репутация подросла.",
    "Ты поймал тот самый вкус, ради которого возвращаются.",
]

BEER_LOSE_LINES = [
    "Кружка выскользнула из рук в самый обидный момент.",
    "Пена пошла не туда. Авторитет тоже.",
    "Бармен посмотрел так, будто ожидал большего.",
    "Ты сделал уверенный глоток. Слишком уверенный.",
    "Стол качнулся. Или это был план?",
    "Кто-то рядом тихо сказал: «бывает».",
    "Кружка была полной. Шанс был хороший. Дальше история грустная.",
    "Сегодня вкус победы оказался просроченным.",
    "Ты промахнулся мимо настроения.",
    "Бар сделал вид, что ничего не видел. Но все видели.",
]

BEER_ZERO_LINES = [
    "Ты сделал вид, что пьешь. Бармен сделал вид, что верит.",
    "Кружка пустая, взгляд уверенный. Странная комбинация.",
    "Ничего не произошло, но пауза была драматичная.",
    "Ты поднял кружку. Кружка подняла вопросы.",
    "Бар замер на секунду. Потом решил не вмешиваться.",
    "Пена была. Смысла не было.",
    "Этот глоток уйдет в архив без последствий.",
    "Ты попытался войти в легенду, но дверь была закрыта.",
    "Бармен записал это как «техническая попытка».",
    "Сегодня без изменений. Зато с выражением лица.",
]

BEER_COOLDOWN_LINES = [
    "Бармен прикрыл кран ладонью. Пауза тоже часть ритуала.",
    "Кружка еще не успела соскучиться.",
    "Тебя узнали у стойки. Сказали: «чуть позже».",
    "Бармен делает вид, что занят. На самом деле считает таймер.",
    "Пена еще не осела после прошлого захода.",
    "Сегодня ты слишком быстрый для этого бара.",
    "Стойка помнит твой последний глоток. И пока не готова забыть.",
    "Кран молчит. Значит, время еще не пришло.",
    "Бармен поднял палец: не спорит, просто ждет.",
    "Кружка на перерыве. У нее тоже график.",
]

BEER_JACKPOT_LINES = [
    "В баре на секунду стало тихо. Потом все поняли почему.",
    "Бармен достал кружку, которую обычно не показывают.",
    "Кран выдал не пену, а легенду.",
    "Кто-то случайно дернул правильный рычаг.",
    "Сегодня банк решил уйти красиво.",
]


async def run_beer_attempt(user_id: int, db: Database, settings: SettingsManager) -> dict[str, Any]:
    cooldown_seconds = settings.beer_cooldown
    last_beer_time = await db.get_last_beer_time(user_id)

    if last_beer_time:
        time_passed = datetime.now() - last_beer_time
        if time_passed.total_seconds() < cooldown_seconds:
            time_left = timedelta(seconds=cooldown_seconds) - time_passed
            return {
                "text": (
                    "⏳ <b>Бар на паузе</b>\n\n"
                    f"{random.choice(BEER_COOLDOWN_LINES)}\n\n"
                    f"{DIVIDER}\n"
                    f"Осталось: <b>{format_time_delta(time_left)}</b>"
                ),
                "jackpot_text": None,
                "spam": False,
            }

    now = datetime.now()
    if user_id in user_spam_tracker:
        if (now - user_spam_tracker[user_id]).total_seconds() < 2.0:
            return {"text": None, "jackpot_text": None, "spam": True}
    user_spam_tracker[user_id] = now

    win_roll = random.randint(1, 100)
    rating_change = 0

    if win_roll > 35:
        rating_change = random.randint(1, 15)
        text = (
            "🍺 <b>Барная попытка</b>\n\n"
            f"{random.choice(BEER_WIN_LINES)}\n\n"
            f"{DIVIDER}\n"
            f"Итог: <b>+{rating_change}</b> 🍺"
        )
    else:
        current_rating = await db.get_user_beer_rating(user_id)
        if current_rating > 0:
            rating_loss = random.randint(1, 10)
            rating_change = -min(current_rating, rating_loss)
            text = (
                "🍺 <b>Барная попытка</b>\n\n"
                f"{random.choice(BEER_LOSE_LINES)}\n\n"
                f"{DIVIDER}\n"
                f"Итог: <b>{rating_change}</b> 🍺"
            )
        else:
            rating_change = random.randint(1, 3)
            text = (
                "🍺 <b>Барная попытка</b>\n\n"
                f"{random.choice(BEER_ZERO_LINES)}\n\n"
                f"{DIVIDER}\n"
                f"Итог: <b>+{rating_change}</b> 🍺"
            )

    if rating_change != 0:
        await db.change_rating(user_id, rating_change)
        if rating_change < 0:
            await db.increase_jackpot(abs(rating_change))

    await db.update_last_beer_time(user_id)

    jackpot_text = None
    if random.randint(1, settings.jackpot_chance) == 1:
        current_jackpot = await db.get_jackpot()
        if current_jackpot > 0:
            await db.reset_jackpot()
            await db.change_rating(user_id, current_jackpot)
            jackpot_text = (
                f"🎉 <b>Джекпот</b>\n\n"
                f"{random.choice(BEER_JACKPOT_LINES)}\n\n"
                f"{DIVIDER}\n"
                f"Бонус: <b>+{current_jackpot}</b> 🍺"
            )

    return {"text": text, "jackpot_text": jackpot_text, "spam": False}

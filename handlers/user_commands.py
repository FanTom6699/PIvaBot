# handlers/user_commands.py
import random
from datetime import datetime, timedelta
from aiogram import Router, Bot, html # ✅ (Импортируем html)
from aiogram.types import Message
from aiogram.filters import Command

from database import Database
from settings import SettingsManager
from .common import check_user_registered
from utils import format_time_delta

# --- ИНИЦИАЛИЗАЦИЯ --
user_commands_router = Router()
user_spam_tracker = {}

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

# --- ✅✅✅ ИСПРАВЛЕННАЯ КОМАНДА /beer ✅✅✅ ---
@user_commands_router.message(Command("beer"))
async def cmd_beer(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    user_id = message.from_user.id
    
    # (Проверка регистрации в группе)
    if message.chat.type != 'private' and not await check_user_registered(message, bot, db):
        return

    # (Проверка кулдауна)
    cooldown_seconds = settings.beer_cooldown
    last_beer_time = await db.get_last_beer_time(user_id)
    
    if last_beer_time:
        time_passed = datetime.now() - last_beer_time
        if time_passed.total_seconds() < cooldown_seconds:
            time_left = timedelta(seconds=cooldown_seconds) - time_passed
            reply_text = f"{random.choice(BEER_COOLDOWN_LINES)}\n\n⏳ {format_time_delta(time_left)}"
            await message.reply(reply_text, parse_mode='HTML')
            return

    # (Проверка спама - Anti-Spam)
    now = datetime.now()
    if user_id in user_spam_tracker:
        if (now - user_spam_tracker[user_id]).total_seconds() < 2.0:
            return # (Просто игнорируем)
    user_spam_tracker[user_id] = now
    
    jackpot_chance = settings.jackpot_chance
    win_roll = random.randint(1, 100)
    
    rating_change = 0
    reply_text = ""
    
    if win_roll > 35: # (65% шанс выиграть: 100 - 65 = 35)
        rating_change = random.randint(1, 15) # ✅ Победа: +1 до +15
        reply_text = f"{random.choice(BEER_WIN_LINES)}\n\n+{rating_change} 🍺"
    else:
        # (Проверяем текущий баланс ПЕРЕД списанием)
        current_rating = await db.get_user_beer_rating(user_id)
        if current_rating > 0:
            rating_loss = random.randint(1, 10) # ✅ Проигрыш: -1 до -10
            # (Не даем уйти в минус)
            rating_change = -min(current_rating, rating_loss) 
            reply_text = f"{random.choice(BEER_LOSE_LINES)}\n\n{rating_change} 🍺"
        else:
            rating_change = 0 # (Не меняем рейтинг)
            reply_text = f"{random.choice(BEER_ZERO_LINES)}\n\n0 🍺"

    # --- ✅✅✅ ИСПРАВЛЕНИЕ: ✅✅✅ ---
    # 1. Сначала меняем рейтинг (если он изменился)
    if rating_change != 0:
        await db.change_rating(user_id, rating_change)
        
    # 2. В любом случае (даже при 0) обновляем таймер
    await db.update_last_beer_time(user_id)
    # --- ---
    
    # (Отправляем результат)
    await message.reply(reply_text, parse_mode='HTML')

    # (Проверка джекпота - этот код не менялся)
    if random.randint(1, jackpot_chance) == 1:
        current_jackpot = await db.get_jackpot()
        if current_jackpot > 0:
            await db.reset_jackpot()
            await db.change_rating(user_id, current_jackpot)
            
            await bot.send_message(
                chat_id=message.chat.id,
                text=f"{random.choice(BEER_JACKPOT_LINES)}\n\n"
                     f"🎉 <b>ДЖЕКПОТ</b>\n"
                     f"+{current_jackpot} 🍺",
                parse_mode='HTML'
            )
# --- ---


@user_commands_router.message(Command("top"))
async def cmd_top(message: Message, bot: Bot, db: Database):
    # (Проверка регистрации в группе)
    if message.chat.type != 'private' and not await check_user_registered(message, bot, db):
        return
        
    top_users = await db.get_top_users()
    if not top_users: 
        return await message.answer("В баре пока никого нет, чтобы составить топ.")

    top_text = "🏆 <b>Топ бара</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, (first_name, last_name, rating) in enumerate(top_users):
        name = html.quote(first_name)
        if last_name:
            name += f" {html.quote(last_name)}"
            
        place = medals[i] if i < len(medals) else f"{i + 1}."
        top_text += f"{place} {name} — {rating} 🍺\n"

    user_rank = await db.get_user_rank(message.from_user.id)
    if user_rank:
        top_text += f"\nТы: #{user_rank['rank']} — {user_rank['rating']} 🍺"
        
    await message.answer(top_text, parse_mode='HTML')


# --- (ТВОЯ НОВАЯ КОМАНДА /start, КОТОРАЯ БЫЛА В user_commands.py) ---
@user_commands_router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot, db: Database):
    user = message.from_user
    
    # (Регистрируем или обновляем инфо)
    await db.add_user(user.id, user.first_name, user.last_name, user.username)
    
    user_profile = await db.get_user_profile(user.id)
    (first_name, last_name, username, rating, reg_date_raw) = user_profile
    
    # --- (Твои статусы) ---
    status = "🧐 Новичок"
    if rating >= 100: status = "🍻 Выпивоха"
    if rating >= 300: status = "🎩 Завсегдатай"
    if rating >= 750: status = "😎 Свой в доску"
    if rating >= 1500: status = "💪 Синяк"
    if rating >= 3000: status = " V.I.P."
    if rating >= 5000: status = "🍾 Сомелье"
    if rating >= 7500: status = "🎗 Ветеран Бара"
    if rating >= 10000: status = "🌟 Легенда Бара"
    if rating >= 15000: status = "🎖 Элита"
    if rating >= 20000: status = "🏆 Чемпион"
    if rating >= 30000: status = "💎 Алмазный Алконафт"
    if rating >= 40000: status = "🌀 Повелитель Пены"
    if rating >= 50000: status = "🌌 Бог Пива"
    if rating >= 65000: status = "🔱 Атлант"
    if rating >= 80000: status = "🦄 Мифический"
    if rating >= 100000: status = "🧙‍♂️ Пивной Магистр"
    if rating >= 150000: status = "🦖 Пивозавр"
    if rating >= 225000: status = "🤖 Барный Киборг"
    if rating >= 300000: status = "🚀 Трижды Несокрушимый"
    if rating >= 400000: status = "⚡️ Гроза Кранов"
    if rating >= 500000: status = "🌪️ Лорд Хмельных Бурь"
    if rating >= 650000: status = "👑 Император Пива"
    if rating >= 800000: status = "🪐 Хозяин Галактики Пива"
    if rating >= 1000000: status = "✨ Пивной Абсолют"
    # --- --- ---

    # Безопасно получаем имя
    user_name = html.quote(user.first_name)

    # Безопасно форматируем дату
    reg_date_str = "Неизвестно"
    if reg_date_raw:
        try:
            reg_date_str = datetime.fromisoformat(reg_date_raw).strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            reg_date_str = "Давно..." # На случай, если в БД старая дата

    # --- ТЕКСТОВЫЙ ПРОФИЛЬ (Без символов рамки) ---
    
    profile_text = (
        f"🍻 <b>ТВОЙ ПРОФИЛЬ</b> 🍻\n\n"
        f"👤 <b>Имя:</b> {user_name}\n"
        f"🏆 <b>Статус:</b> {status}\n"
        f"🍺 <b>Рейтинг:</b> {rating}\n\n"
        f"🗓 <b>В баре c:</b> {reg_date_str}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n\n"
        f"<i>Напиши <code>/help</code>, чтобы узнать все команды.</i>"
    )
    
    await message.answer(profile_text, parse_mode='HTML')

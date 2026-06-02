# handlers/common.py
from datetime import datetime, timedelta
from html import escape

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.filters.callback_data import CallbackData
from database import Database
from settings import SettingsManager
from .beer_service import run_beer_attempt
from utils import format_time_delta

common_router = Router()
DIVIDER = "<code>--- --- ---</code>"


class MainMenuCallback(CallbackData, prefix="menu"):
    action: str


def get_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🍺 Выпить", callback_data=MainMenuCallback(action="beer").pack()),
            InlineKeyboardButton(text="👤 Профиль", callback_data=MainMenuCallback(action="profile").pack()),
        ],
        [
            InlineKeyboardButton(text="🏆 Топ", callback_data=MainMenuCallback(action="top").pack()),
            InlineKeyboardButton(text="🌾 Ферма", callback_data=f"farm:main_dashboard:{user_id}"),
        ],
        [
            InlineKeyboardButton(text="🎁 Джекпот", callback_data=MainMenuCallback(action="jackpot").pack()),
            InlineKeyboardButton(text="❓ Помощь", callback_data=MainMenuCallback(action="help").pack()),
        ],
    ])


def get_back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Назад в меню", callback_data=MainMenuCallback(action="home").pack())
    ]])


def get_private_start_text(user_name: str, is_new: bool) -> str:
    user_name = escape(user_name)
    if is_new:
        return (
            f"🍺 <b>Пивная</b>\n\n"
            f"Добро пожаловать, <b>{user_name}</b>.\n"
            "Бар открыт, первая кружка ждет.\n\n"
            f"{DIVIDER}\n"
            "Выбирай действие ниже и начинай набивать репутацию."
        )
    return (
        f"🍺 <b>Пивная</b>\n\n"
        f"С возвращением, <b>{user_name}</b>.\n"
        "Бар на месте. Кружка ждет.\n\n"
        f"{DIVIDER}\n"
        "Меню стойки ниже."
    )


async def get_profile_text(user_id: int, user_name: str, db: Database, settings: SettingsManager | None = None) -> str:
    user_name = escape(user_name)
    profile = await db.get_user_profile(user_id)
    rating = profile[3] if profile else 0
    rank = await db.get_user_rank(user_id)
    rank_text = f"#{rank['rank']}" if rank else "—"
    farm = await db.get_user_farm_data(user_id)
    inventory = await db.get_user_inventory(user_id)
    last_beer_time = await db.get_last_beer_time(user_id)
    beer_status = "готово"
    if last_beer_time and settings:
        time_passed = datetime.now() - last_beer_time
        if time_passed.total_seconds() < settings.beer_cooldown:
            time_left = timedelta(seconds=settings.beer_cooldown) - time_passed
            beer_status = f"через {format_time_delta(time_left)}"

    return (
        f"👤 <b>Профиль</b>\n\n"
        f"<b>{user_name}</b>\n"
        f"{DIVIDER}\n"
        f"Статус: <b>{get_rating_title(rating)}</b>\n"
        f"Рейтинг: <b>{rating}</b> 🍺\n"
        f"Место: <b>{rank_text}</b>\n\n"
        f"🍺 <b>Бар:</b> {beer_status}\n\n"
        f"🌾 <b>Ферма</b>\n"
        f"Поле: ур. <b>{farm.get('field_level', 1)}</b>\n"
        f"Пивоварня: ур. <b>{farm.get('brewery_level', 1)}</b>\n"
        f"Склад: <b>{inventory.get('зерно', 0)}</b> 🌾 / <b>{inventory.get('хмель', 0)}</b> 🌱"
    )


def get_rating_title(rating: int) -> str:
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
    return status


async def get_top_text(db: Database, user_id: int | None = None) -> str:
    top_users = await db.get_top_users()
    if not top_users:
        return (
            "🏆 <b>Топ бара</b>\n\n"
            "В баре пока тихо.\n\n"
            f"{DIVIDER}\n"
            "Первый рейтинг появится после команды <code>/beer</code>."
        )

    text = (
        "🏆 <b>Топ бара</b>\n\n"
        "Самые заметные гости у стойки.\n\n"
        f"{DIVIDER}\n"
    )
    medals = ["🥇", "🥈", "🥉"]
    for i, (first_name, last_name, rating) in enumerate(top_users):
        name = first_name or "Игрок"
        if last_name:
            name += f" {last_name}"
        name = escape(name)
        place = medals[i] if i < len(medals) else f"{i + 1}."
        text += f"{place} {name} — {rating} 🍺\n"

    if user_id:
        rank = await db.get_user_rank(user_id)
        if rank:
            text += f"\n{DIVIDER}\nТы: <b>#{rank['rank']}</b> — <b>{rank['rating']}</b> 🍺"
    return text


def get_jackpot_text(current_jackpot: int) -> str:
    return (
        "🎁 <b>Джекпот бара</b>\n\n"
        "Общий банк всех чатов.\n"
        "Когда в <code>/beer</code> выпадает минус, потерянные 🍺 уходят сюда.\n\n"
        f"{DIVIDER}\n"
        f"В банке: <b>{current_jackpot}</b> 🍺\n\n"
        "<i>Сорвать джекпот может любой удачный гость при следующей попытке.</i>"
    )


def get_help_text() -> str:
    return (
        "❓ <b>Помощь</b>\n\n"
        "Карта бара и основные команды.\n\n"
        f"{DIVIDER}\n"
        "<b>Основное:</b>\n"
        "• <code>/start</code> - Зарегистрироваться или проверить свой профиль.\n"
        "• <code>/beer</code> - Испытать удачу (раз в 2 часа).\n"
        "• <code>/top</code> - Показать таблицу лидеров.\n"
        "• <code>/jackpot</code> - Проверить текущий джекпот.\n\n"
        f"{DIVIDER}\n"
        "<b>Мини-игры:</b>\n"
        "• <code>/roulette &lt;ставка&gt; &lt;игроки&gt;</code> - Запустить 'Пивную рулетку' в группе.\n"
        "• <code>/ladder &lt;ставка&gt;</code> - Начать игру в 'Пивную лесенку'.\n\n"
        f"{DIVIDER}\n"
        "<b>Прочее:</b>\n"
        "• <code>/id</code> - Узнать свой User ID и ID текущего чата."
    )


# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ РЕГИСТРАЦИИ (ТВОЙ ТЕКСТ) ---
async def check_user_registered(message_or_callback: Message | CallbackQuery, bot: Bot, db: Database) -> bool:
    user = message_or_callback.from_user
    if await db.user_exists(user.id):
        return True
    
    me = await bot.get_me()
    start_link = f"https://t.me/{me.username}?start=register"
    
    # Твои крутые изменения:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➡️ Зайти в бар (Регистрация)", url=start_link)]])
    text = (
        "<b>Постой, незнакомец!</b> 🍻\n\n"
        "Я тебя здесь раньше не видел. Нужно сперва заглянуть ко мне в личку, чтобы я тебя 'записал' в наш клуб.\n\n"
        "Нажми кнопку ⬇️, чтобы зайти."
    )
    
    if isinstance(message_or_callback, Message):
        await message_or_callback.reply(text, reply_markup=keyboard, parse_mode='HTML')
    else:
        # Для inline-кнопок (рулетка, лесенка и т.д.)
        await message_or_callback.answer("Сначала нужно зарегистрироваться!", show_alert=True)
        await bot.send_message(message_or_callback.message.chat.id, text, reply_markup=keyboard, parse_mode='HTML')
    return False

# --- ОБРАБОТЧИКИ СОБЫТИЙ ЧАТА (без изменений) ---
@common_router.my_chat_member()
async def handle_bot_membership(event: ChatMemberUpdated, bot: Bot, db: Database):
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    if old_status in ("left", "kicked") and new_status in ("member", "administrator"):
        await db.add_chat(event.chat.id, event.chat.title)
    elif old_status in ("member", "administrator") and new_status in ("left", "kicked"):
        await db.remove_chat(event.chat.id)

# --- КОМАНДЫ ПОЛЬЗОВАТЕЛЕЙ (ТВОЙ ТЕКСТ) ---
@common_router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, db: Database):
    user = message.from_user
    if message.chat.type != "private":
        me = await bot.get_me()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🍺 Открыть меню", url=f"https://t.me/{me.username}?start=menu")
        ]])
        await message.reply(
            "Меню бара открывается в личке.",
            reply_markup=keyboard,
            parse_mode='HTML'
        )
        return

    is_new = not await db.user_exists(user.id)
    if is_new:
        await db.add_user(user.id, user.first_name, user.last_name, user.username)
    else:
        await db.add_user(user.id, user.first_name, user.last_name, user.username)

    await message.answer(
        get_private_start_text(user.full_name, is_new),
        reply_markup=get_main_menu_keyboard(user.id),
        parse_mode='HTML'
    )

@common_router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(get_help_text(), parse_mode='HTML')


@common_router.callback_query(MainMenuCallback.filter())
async def cq_main_menu(callback: CallbackQuery, callback_data: MainMenuCallback, db: Database, settings: SettingsManager):
    user = callback.from_user
    await db.add_user(user.id, user.first_name, user.last_name, user.username)

    if callback_data.action == "home":
        text = get_private_start_text(user.full_name, False)
        keyboard = get_main_menu_keyboard(user.id)
    elif callback_data.action == "profile":
        text = await get_profile_text(user.id, user.full_name, db, settings)
        keyboard = get_back_to_menu_keyboard()
    elif callback_data.action == "top":
        text = await get_top_text(db, user.id)
        keyboard = get_back_to_menu_keyboard()
    elif callback_data.action == "jackpot":
        current_jackpot = await db.get_jackpot()
        text = get_jackpot_text(current_jackpot)
        keyboard = get_back_to_menu_keyboard()
    elif callback_data.action == "help":
        text = get_help_text()
        keyboard = get_back_to_menu_keyboard()
    elif callback_data.action == "beer":
        result = await run_beer_attempt(user.id, db, settings)
        if result["spam"]:
            await callback.answer()
            return
        text = result["text"]
        if result["jackpot_text"]:
            text += f"\n\n{result['jackpot_text']}"
        keyboard = get_back_to_menu_keyboard()
    else:
        text = get_private_start_text(user.full_name, False)
        keyboard = get_main_menu_keyboard(user.id)

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    await callback.answer()

@common_router.message(Command("id"))
async def cmd_id(message: Message):
    await message.reply(
        f"ℹ️ <b>Информация</b>\n\n"
        f"{DIVIDER}\n"
        f"👤 User ID: <code>{message.from_user.id}</code>\n"
        f"💬 Chat ID: <code>{message.chat.id}</code>",
        parse_mode='HTML'
    )

@common_router.message(Command("jackpot"))
async def cmd_jackpot(message: Message, db: Database):
    current_jackpot = await db.get_jackpot()
    await message.answer(get_jackpot_text(current_jackpot), parse_mode='HTML')

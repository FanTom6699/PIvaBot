# handlers/common.py
from html import escape

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.filters.callback_data import CallbackData
from database import Database

common_router = Router()


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
            f"🍺 <b>Добро пожаловать в Пивную, {user_name}.</b>\n\n"
            "Твоя кружка пока пустая, но бар уже открыт.\n"
            "Жми кнопку ниже и начинай набивать репутацию."
        )
    return (
        f"🍺 <b>С возвращением, {user_name}.</b>\n\n"
        "Бар на месте. Кружка ждет."
    )


async def get_profile_text(user_id: int, user_name: str, db: Database) -> str:
    user_name = escape(user_name)
    profile = await db.get_user_profile(user_id)
    rating = profile[3] if profile else 0
    rank = await db.get_user_rank(user_id)
    rank_text = f"#{rank['rank']}" if rank else "—"
    return (
        f"🍺 <b>{user_name}</b>\n\n"
        f"Рейтинг: {rating} 🍺\n"
        f"Место: {rank_text}"
    )


async def get_top_text(db: Database, user_id: int | None = None) -> str:
    top_users = await db.get_top_users()
    if not top_users:
        return "В баре пока никого нет, чтобы составить топ."

    text = "🏆 <b>Топ бара</b>\n\n"
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
            text += f"\nТы: #{rank['rank']} — {rank['rating']} 🍺"
    return text


def get_help_text() -> str:
    return (
        "<b>🍻 Меню Бара (Помощь) 🍻</b>\n\n"
        "Запутался? Не беда, вот наша 'карта'.\n\n"
        "--- --- ---\n"
        "<b>Основное:</b>\n"
        "• <code>/start</code> - Зарегистрироваться или проверить свой профиль.\n"
        "• <code>/beer</code> - Испытать удачу (раз в 2 часа).\n"
        "• <code>/top</code> - Показать таблицу лидеров.\n"
        "• <code>/jackpot</code> - Проверить текущий джекпот.\n\n"
        "--- --- ---\n"
        "<b>Мини-игры:</b>\n"
        "• <code>/roulette &lt;ставка&gt; &lt;игроки&gt;</code> - Запустить 'Пивную рулетку' в группе.\n"
        "• <code>/ladder &lt;ставка&gt;</code> - Начать игру в 'Пивную лесенку'.\n\n"
        "--- --- ---\n"
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
async def cq_main_menu(callback: CallbackQuery, callback_data: MainMenuCallback, db: Database):
    user = callback.from_user
    await db.add_user(user.id, user.first_name, user.last_name, user.username)

    if callback_data.action == "home":
        text = get_private_start_text(user.full_name, False)
        keyboard = get_main_menu_keyboard(user.id)
    elif callback_data.action == "profile":
        text = await get_profile_text(user.id, user.full_name, db)
        keyboard = get_back_to_menu_keyboard()
    elif callback_data.action == "top":
        text = await get_top_text(db, user.id)
        keyboard = get_back_to_menu_keyboard()
    elif callback_data.action == "jackpot":
        current_jackpot = await db.get_jackpot()
        text = (
            "🎁 <b>Джекпот бара</b>\n\n"
            f"В банке: {current_jackpot} 🍺"
        )
        keyboard = get_back_to_menu_keyboard()
    elif callback_data.action == "help":
        text = get_help_text()
        keyboard = get_back_to_menu_keyboard()
    elif callback_data.action == "beer":
        text = "Напиши /beer в личке или группе, чтобы испытать удачу."
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
        f"ℹ️ **Информация:**\n\n"
        f"👤 Ваш User ID: <code>{message.from_user.id}</code>\n"
        f"💬 ID этого чата: <code>{message.chat.id}</code>",
        parse_mode='HTML'
    )

@common_router.message(Command("jackpot"))
async def cmd_jackpot(message: Message, db: Database):
    current_jackpot = await db.get_jackpot()
    await message.answer(
        f"💰 <b>Текущий Джекпот</b> 💰\n\n"
        f"В банке сейчас накоплено: <b>{current_jackpot} 🍺</b>\n\n"
        f"<i>Каждый проигрыш в <code>/beer</code> пополняет банк, и каждый, кто нажимает <code>/beer</code>, может его сорвать!</i>",
        parse_mode='HTML'
    )

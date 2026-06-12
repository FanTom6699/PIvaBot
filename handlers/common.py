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
from .text_aliases import HELP_ALIASES, JACKPOT_ALIASES, GroupTextAlias
from utils import answer_to_trigger, format_time_delta, mention_user, mention_user_from_parts

common_router = Router()
DIVIDER = "<code>--- --- ---</code>"
GUIDE_URL = "https://pivnoybaron.uz"


class MainMenuCallback(CallbackData, prefix="menu"):
    action: str


class ChatTopCallback(CallbackData, prefix="chat_top"):
    chat_id: int


def get_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🍺 Выпить", callback_data=MainMenuCallback(action="beer").pack()),
            InlineKeyboardButton(text="👤 Профиль", callback_data=MainMenuCallback(action="profile").pack()),
        ],
        [
            InlineKeyboardButton(text="🏆 Рейтинг", callback_data=MainMenuCallback(action="rating").pack()),
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


def get_guide_keyboard(show_main_menu: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="📘 Справочник команд", url=GUIDE_URL)]]
    if show_main_menu:
        rows.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data=MainMenuCallback(action="home").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_rating_keyboard(show_main_menu: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🍺 Пиво", callback_data=MainMenuCallback(action="rating_beer").pack())],
        [
            InlineKeyboardButton(text="🌾 Зерно", callback_data=MainMenuCallback(action="rating_grain").pack()),
            InlineKeyboardButton(text="🌱 Хмель", callback_data=MainMenuCallback(action="rating_hops").pack()),
        ],
    ]
    if show_main_menu:
        rows.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data=MainMenuCallback(action="home").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_back_to_rating_keyboard(show_main_menu: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="⬅️ Назад к рейтингу", callback_data=MainMenuCallback(action="rating").pack())],
    ]
    if show_main_menu:
        rows.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data=MainMenuCallback(action="home").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def crop_button_text(text: str, limit: int = 32) -> str:
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


def get_chat_top_picker_keyboard(chats) -> InlineKeyboardMarkup:
    rows = []
    for chat_id, title in chats:
        chat_title = crop_button_text(title or f"Чат {chat_id}")
        rows.append([InlineKeyboardButton(
            text=f"💬 {chat_title}",
            callback_data=ChatTopCallback(chat_id=chat_id).pack()
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data=MainMenuCallback(action="home").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_chat_top_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к чатам", callback_data=MainMenuCallback(action="chat_top_picker").pack())],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data=MainMenuCallback(action="home").pack())],
    ])


def get_profile_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return get_back_to_menu_keyboard()


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


def get_beer_status(last_beer_time: datetime | None, settings: SettingsManager | None) -> str:
    if last_beer_time and settings:
        time_passed = datetime.now() - last_beer_time
        if time_passed.total_seconds() < settings.beer_cooldown:
            time_left = timedelta(seconds=settings.beer_cooldown) - time_passed
            return f"через {format_time_delta(time_left)}"
    return "готово"


def format_registration_date(created_at: str | None) -> str:
    if not created_at:
        return "—"
    try:
        return datetime.fromisoformat(created_at).strftime("%d.%m.%Y")
    except ValueError:
        return "—"


async def get_farm_profile_status(user_id: int, db: Database, show_inventory: bool = False) -> str:
    from .farm_config import BARN_CAPACITY, BARN_ITEMS, SILO_CAPACITY, SILO_ITEMS, START_FIELD_COUNT

    inventory = await db.get_user_inventory(user_id)
    plots = await db.get_user_plots(user_id)
    chickens = await db.get_user_chickens(user_id)
    now = datetime.now()

    ready_plots = 0
    growing_plots = 0
    for plot_number, _, ready_time in plots:
        if plot_number > START_FIELD_COUNT:
            continue
        try:
            ready_dt = datetime.fromisoformat(ready_time) if isinstance(ready_time, str) else ready_time
        except ValueError:
            continue

        if ready_dt and now >= ready_dt:
            ready_plots += 1
        elif ready_dt:
            growing_plots += 1

    ready_eggs = sum(1 for chicken in chickens if chicken.get("state") == "ready")
    producing = sum(1 for chicken in chickens if chicken.get("state") == "producing")
    needs_feed = sum(1 for chicken in chickens if chicken.get("state") == "needs_feed")
    chicken_status = f"{ready_eggs} готово / {producing} производят / {needs_feed} ждут корм"

    silo_used = sum(max(0, int(inventory.get(item_id, 0))) for item_id, _ in SILO_ITEMS)
    barn_used = sum(max(0, int(inventory.get(item_id, 0))) for item_id, _ in BARN_ITEMS)

    lines = [
        f"Поля: <b>{START_FIELD_COUNT}</b>",
        f"Грядки: <b>{ready_plots}</b> готово / <b>{growing_plots}</b> растет",
        f"Курятник: <b>{chicken_status}</b>",
    ]

    if show_inventory:
        lines.append(f"Силос: <b>{silo_used} / {SILO_CAPACITY}</b>")
        lines.append(f"Амбар: <b>{barn_used} / {BARN_CAPACITY}</b>")

    return "\n".join(lines)


async def get_profile_text(user_id: int, user_name: str, db: Database, settings: SettingsManager | None = None) -> str:
    user_name = mention_user(user_id, user_name)
    profile = await db.get_user_profile(user_id)
    rating = profile[3] if profile else 0
    xp = profile[7] if profile and len(profile) > 7 and profile[7] is not None else 0
    registration_date = format_registration_date(profile[5] if profile else None)
    rank = await db.get_user_rank(user_id)
    rank_text = f"#{rank['rank']}" if rank else "—"
    level, title = get_xp_level(xp)
    xp_progress = format_xp_progress(level, xp)

    return (
        f"👤 <b>Профиль</b>\n\n"
        f"<b>{user_name}</b>\n"
        f"{DIVIDER}\n"
        f"Уровень: <b>{level}</b> — <b>{title}</b>\n"
        f"Опыт: <b>{xp_progress}</b> ⭐\n"
        f"Пиво: <b>{rating}</b> 🍺\n"
        f"Место: <b>{rank_text}</b>\n"
        f"В баре с: <b>{registration_date}</b>"
    )


async def get_compact_profile_text(user_id: int, user_name: str, db: Database, settings: SettingsManager | None = None) -> str:
    user_name = mention_user(user_id, user_name)
    profile = await db.get_user_profile(user_id)
    rating = profile[3] if profile else 0
    xp = profile[7] if profile and len(profile) > 7 and profile[7] is not None else 0
    registration_date = format_registration_date(profile[5] if profile else None)
    rank = await db.get_user_rank(user_id)
    rank_text = f"#{rank['rank']}" if rank else "—"
    level, title = get_xp_level(xp)

    return (
        f"👤 <b>{user_name}</b>\n\n"
        f"Ур. <b>{level}</b> — <b>{title}</b>\n"
        f"XP: <b>{xp}</b> ⭐\n"
        f"Пиво: <b>{rating}</b> 🍺\n"
        f"Место в топе: <b>{rank_text}</b>\n"
        f"В баре с: <b>{registration_date}</b>"
    )


XP_LEVELS = [
    (1, 0),
    (2, 50),
    (3, 120),
    (4, 220),
    (5, 350),
    (6, 500),
    (7, 700),
    (8, 950),
    (9, 1250),
    (10, 1600),
    (11, 2000),
    (12, 2450),
    (13, 2950),
    (14, 3500),
    (15, 4100),
    (16, 4800),
    (17, 5600),
    (18, 6500),
    (19, 7500),
    (20, 8600),
]

LEVEL_TITLES = {
    1: "🧐 Новичок",
    5: "🍻 Выпивоха",
    10: "🎩 Завсегдатай",
    15: "🍺 Пивовар",
    20: "🏭 Мастер пивоварни",
}


def get_xp_level(xp: int) -> tuple[int, str]:
    xp = max(0, xp)
    level = 1
    for level_number, threshold in XP_LEVELS:
        if xp >= threshold:
            level = level_number

    title_level = max(title_level for title_level in LEVEL_TITLES if title_level <= level)
    return level, LEVEL_TITLES[title_level]


def get_next_level_xp(level: int) -> int | None:
    for level_number, threshold in XP_LEVELS:
        if level_number > level:
            return threshold
    return None


def format_xp_progress(level: int, xp: int) -> str:
    next_xp = get_next_level_xp(level)
    if next_xp is None:
        return f"{xp} / max"
    return f"{xp} / {next_xp}"


async def get_top_text(db: Database, user_id: int | None = None) -> str:
    top_users = await db.get_top_users()
    if not top_users:
        return (
            "🏆 <b>Рейтинг: 🍺 Пиво</b>\n\n"
            "В баре пока тихо.\n\n"
            f"{DIVIDER}\n"
            "Первый рейтинг появится после команды <code>/beer</code>."
        )

    text = (
        "🏆 <b>Рейтинг: 🍺 Пиво</b>\n\n"
        "Глобальный рейтинг игроков по 🍺.\n\n"
        f"{DIVIDER}\n"
    )
    medals = ["🥇", "🥈", "🥉"]
    for i, (top_user_id, first_name, last_name, rating) in enumerate(top_users):
        name = mention_user_from_parts(top_user_id, first_name, last_name)
        place = medals[i] if i < len(medals) else f"{i + 1}."
        text += f"{place} {name} — {rating} 🍺\n"

    if user_id:
        rank = await db.get_user_rank(user_id)
        if rank:
            text += f"\n{DIVIDER}\nТы: <b>#{rank['rank']}</b> — <b>{rank['rating']}</b> 🍺"
    return text


async def get_chat_top_text(db: Database, chat_id: int, user_id: int | None = None, chat_title: str | None = None) -> str:
    title_text = escape(chat_title) if chat_title else "этот чат"
    top_users = await db.get_chat_top_users(chat_id)
    if not top_users:
        return (
            "🏆 <b>Топ пива в чате</b>\n\n"
            f"Чат: <b>{title_text}</b>\n\n"
            "Пока нет игроков в топе.\n\n"
            f"{DIVIDER}\n"
            "Первый результат появится после команды <code>/beer</code>."
        )

    text = (
        "🏆 <b>Топ пива в чате</b>\n\n"
        f"Чат: <b>{title_text}</b>\n"
        "Текущий топ игроков по 🍺.\n\n"
        f"{DIVIDER}\n"
    )
    medals = ["🥇", "🥈", "🥉"]
    for i, (top_user_id, first_name, last_name, rating) in enumerate(top_users):
        name = mention_user_from_parts(top_user_id, first_name, last_name)
        place = medals[i] if i < len(medals) else f"{i + 1}."
        text += f"{place} {name} — <b>{rating}</b> 🍺\n"

    if user_id:
        rank = await db.get_user_chat_rank(user_id, chat_id)
        if rank:
            text += f"\n{DIVIDER}\nТы в этом чате: <b>#{rank['rank']}</b> — <b>{rank['rating']}</b> 🍺"
    return text


def get_chat_top_picker_text(chats) -> str:
    if not chats:
        return (
            "🏆 <b>Топы чатов</b>\n\n"
            "Пока нет общих чатов для выбора.\n\n"
            f"{DIVIDER}\n"
            "Напиши <code>/beer</code> или <code>/me</code> в группе, где есть бот, и этот чат появится здесь."
        )

    return (
        "🏆 <b>Топы чатов</b>\n\n"
        "Выбери чат, чей топ пива показать.\n\n"
        f"{DIVIDER}\n"
        "Показываются только группы, где есть бот и где ты уже использовал команды."
    )


async def get_available_user_chats(db: Database, bot: Bot, user_id: int):
    chats = await db.get_user_chats(user_id)
    available_chats = []
    for chat_id, title in chats:
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except Exception:
            continue
        if member.status not in ("left", "kicked"):
            available_chats.append((chat_id, title))
    return available_chats


def get_rating_menu_text() -> str:
    return (
        "🏆 <b>Рейтинг</b>\n\n"
        "Выбери таблицу.\n\n"
        f"{DIVIDER}\n"
        "🍺 <b>Пиво</b> — глобальный рейтинг.\n"
        "🌾 <b>Зерно</b> — всего собрано зерна.\n"
        "🌱 <b>Хмель</b> — всего собрано хмеля."
    )


async def get_harvest_rating_text(db: Database, user_id: int | None, product_id: str) -> str:
    config = {
        "зерно": {"emoji": "🌾", "title": "Зерно"},
        "хмель": {"emoji": "🌱", "title": "Хмель"},
    }
    item = config[product_id]
    top_users = await db.get_top_harvest(product_id)

    if not top_users:
        return (
            f"🏆 <b>Рейтинг: {item['emoji']} {item['title']}</b>\n\n"
            "Пока никто не собрал этот ресурс.\n\n"
            f"{DIVIDER}\n"
            "Первый результат появится после сбора урожая на ферме."
        )

    text = (
        f"🏆 <b>Рейтинг: {item['emoji']} {item['title']}</b>\n\n"
        f"Всего собрано за всё время.\n\n"
        f"{DIVIDER}\n"
    )
    medals = ["🥇", "🥈", "🥉"]
    for i, (top_user_id, first_name, last_name, total) in enumerate(top_users):
        name = mention_user_from_parts(top_user_id, first_name, last_name)
        place = medals[i] if i < len(medals) else f"{i + 1}."
        text += f"{place} {name} — <b>{total}</b> {item['emoji']}\n"

    if user_id:
        rank = await db.get_user_harvest_rank(user_id, product_id)
        if rank:
            text += f"\n{DIVIDER}\nТы: <b>#{rank['rank']}</b> — <b>{rank['total']}</b> {item['emoji']}"
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
        "📘 <b>Справочник PIvaBot</b>\n\n"
        "Полный список команд, фраз без слэша, ферма, рейтинги и мини-игры находятся тут.\n\n"
        f"{DIVIDER}\n"
        "Нажми кнопку ниже, чтобы открыть справочник команд."
    )


# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ РЕГИСТРАЦИИ (ТВОЙ ТЕКСТ) ---
async def check_user_registered(message_or_callback: Message | CallbackQuery, bot: Bot, db: Database) -> bool:
    user = message_or_callback.from_user
    if await db.user_exists(user.id):
        chat = message_or_callback.chat if isinstance(message_or_callback, Message) else message_or_callback.message.chat
        if chat.type != "private":
            await db.add_user_to_chat(chat.id, user.id, chat.title)
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
    await answer_to_trigger(
        message,
        get_help_text(),
        reply_markup=get_guide_keyboard(message.chat.type == "private"),
        parse_mode='HTML'
    )


@common_router.message(GroupTextAlias(*HELP_ALIASES))
async def alias_help(message: Message):
    await cmd_help(message)


@common_router.callback_query(MainMenuCallback.filter())
async def cq_main_menu(callback: CallbackQuery, callback_data: MainMenuCallback, bot: Bot, db: Database, settings: SettingsManager):
    user = callback.from_user
    await db.add_user(user.id, user.first_name, user.last_name, user.username)

    if callback_data.action == "home":
        if callback.message.chat.type != "private":
            await callback.answer("Главное меню открывается в личке с ботом.", show_alert=True)
            return
        text = get_private_start_text(user.full_name, False)
        keyboard = get_main_menu_keyboard(user.id)
    elif callback_data.action == "profile":
        text = await get_profile_text(user.id, user.full_name, db, settings)
        keyboard = get_profile_keyboard(user.id)
    elif callback_data.action == "rating":
        text = get_rating_menu_text()
        keyboard = get_rating_keyboard(callback.message.chat.type == "private")
    elif callback_data.action == "chat_top_picker":
        chats = await get_available_user_chats(db, bot, user.id)
        text = get_chat_top_picker_text(chats)
        keyboard = get_chat_top_picker_keyboard(chats)
    elif callback_data.action == "rating_beer":
        text = await get_top_text(db, user.id)
        keyboard = get_back_to_rating_keyboard(callback.message.chat.type == "private")
    elif callback_data.action == "rating_grain":
        text = await get_harvest_rating_text(db, user.id, "зерно")
        keyboard = get_back_to_rating_keyboard(callback.message.chat.type == "private")
    elif callback_data.action == "rating_hops":
        text = await get_harvest_rating_text(db, user.id, "хмель")
        keyboard = get_back_to_rating_keyboard(callback.message.chat.type == "private")
    elif callback_data.action == "jackpot":
        current_jackpot = await db.get_jackpot()
        text = get_jackpot_text(current_jackpot)
        keyboard = get_back_to_menu_keyboard()
    elif callback_data.action == "help":
        text = get_help_text()
        keyboard = get_guide_keyboard(callback.message.chat.type == "private")
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


@common_router.callback_query(ChatTopCallback.filter())
async def cq_chat_top(callback: CallbackQuery, callback_data: ChatTopCallback, bot: Bot, db: Database):
    chat = await db.get_user_chat(callback.from_user.id, callback_data.chat_id)
    if not chat:
        await callback.answer("Этот чат пока недоступен для тебя.", show_alert=True)
        return

    try:
        member = await bot.get_chat_member(chat[0], callback.from_user.id)
    except Exception:
        await callback.answer("Не могу проверить этот чат.", show_alert=True)
        return

    if member.status in ("left", "kicked"):
        await callback.answer("Ты уже не в этом чате.", show_alert=True)
        return

    text = await get_chat_top_text(db, chat[0], callback.from_user.id, chat[1])
    await callback.message.edit_text(
        text,
        reply_markup=get_chat_top_back_keyboard(),
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
    await answer_to_trigger(message, get_jackpot_text(current_jackpot), parse_mode='HTML')


@common_router.message(GroupTextAlias(*JACKPOT_ALIASES))
async def alias_jackpot(message: Message, db: Database):
    await cmd_jackpot(message, db)

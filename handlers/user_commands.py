# handlers/user_commands.py
from aiogram import Router, Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.filters import Command

from database import Database
from settings import SettingsManager
from utils import answer_to_trigger
from .beer_service import run_beer_attempt
from .common import (
    check_user_registered,
    get_available_user_chats,
    get_chat_top_picker_keyboard,
    get_chat_top_picker_text,
    get_chat_top_text,
    get_compact_profile_text,
    get_profile_keyboard,
    get_profile_text,
    get_rating_keyboard,
    get_rating_menu_text,
)
from .text_aliases import (
    BEER_ALIASES,
    CHAT_TOP_ALIASES,
    GLOBAL_RATING_ALIASES,
    GroupTextAlias,
    PROFILE_ALIASES,
)

# --- ИНИЦИАЛИЗАЦИЯ --
user_commands_router = Router()


async def send_private_rating_prompt(message: Message, bot: Bot):
    me = await bot.get_me()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏆 Открыть рейтинг", url=f"https://t.me/{me.username}?start=menu")
    ]])
    text = (
        "🏆 <b>Глобальный рейтинг</b>\n\n"
        "Общий рейтинг открывается в личке с ботом.\n"
        "Там можно выбрать 🍺 пиво, 🌾 зерно или 🌱 хмель."
    )
    await answer_to_trigger(message, text, reply_markup=keyboard, parse_mode='HTML')

# --- ✅✅✅ ИСПРАВЛЕННАЯ КОМАНДА /beer ✅✅✅ ---
@user_commands_router.message(Command("beer"))
async def cmd_beer(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    user_id = message.from_user.id

    # (Проверка регистрации в группе)
    if message.chat.type != 'private' and not await check_user_registered(message, bot, db):
        return

    result = await run_beer_attempt(user_id, db, settings)
    if result["spam"]:
        return

    await message.reply(result["text"], parse_mode='HTML')

    if result["jackpot_text"]:
        await bot.send_message(
            chat_id=message.chat.id,
            text=result["jackpot_text"],
            parse_mode='HTML'
        )
# --- ---


@user_commands_router.message(GroupTextAlias(*BEER_ALIASES))
async def alias_beer(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    await cmd_beer(message, bot, db, settings)


@user_commands_router.message(Command("top"))
async def cmd_top(message: Message, bot: Bot, db: Database):
    # (Проверка регистрации в группе)
    if message.chat.type != 'private' and not await check_user_registered(message, bot, db):
        return

    if message.chat.type == 'private':
        user = message.from_user
        await db.add_user(user.id, user.first_name, user.last_name, user.username)
        chats = await get_available_user_chats(db, bot, user.id)
        await answer_to_trigger(
            message,
            get_chat_top_picker_text(chats),
            reply_markup=get_chat_top_picker_keyboard(chats),
            parse_mode='HTML'
        )
    else:
        text = await get_chat_top_text(db, message.chat.id, message.from_user.id, message.chat.title)
        await answer_to_trigger(message, text, parse_mode='HTML')


@user_commands_router.message(GroupTextAlias(*CHAT_TOP_ALIASES))
async def alias_top(message: Message, bot: Bot, db: Database):
    await cmd_top(message, bot, db)


@user_commands_router.message(Command("rating"))
async def cmd_rating(message: Message, bot: Bot, db: Database):
    if message.chat.type != 'private':
        await send_private_rating_prompt(message, bot)
        return

    user = message.from_user
    await db.add_user(user.id, user.first_name, user.last_name, user.username)
    await answer_to_trigger(
        message,
        get_rating_menu_text(),
        reply_markup=get_rating_keyboard(),
        parse_mode='HTML'
    )


@user_commands_router.message(GroupTextAlias(*GLOBAL_RATING_ALIASES))
async def alias_rating(message: Message, bot: Bot):
    await send_private_rating_prompt(message, bot)


@user_commands_router.message(Command("me"))
async def cmd_me(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    if message.chat.type != 'private' and not await check_user_registered(message, bot, db):
        return

    user = message.from_user
    await db.add_user(user.id, user.first_name, user.last_name, user.username)
    if message.chat.type == 'private':
        text = await get_profile_text(user.id, user.full_name, db, settings)
        await answer_to_trigger(message, text, reply_markup=get_profile_keyboard(user.id), parse_mode='HTML')
    else:
        text = await get_compact_profile_text(user.id, user.full_name, db, settings)
        await answer_to_trigger(message, text, parse_mode='HTML')


@user_commands_router.message(GroupTextAlias(*PROFILE_ALIASES))
async def alias_me(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    await cmd_me(message, bot, db, settings)


# --- ПРОФИЛЬ ---
@user_commands_router.message(Command("profile"))
async def cmd_profile(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    user = message.from_user
    await db.add_user(user.id, user.first_name, user.last_name, user.username)
    if message.chat.type == 'private':
        text = await get_profile_text(user.id, user.full_name, db, settings)
        await answer_to_trigger(message, text, reply_markup=get_profile_keyboard(user.id), parse_mode='HTML')
    else:
        text = await get_compact_profile_text(user.id, user.full_name, db, settings)
        await answer_to_trigger(message, text, parse_mode='HTML')

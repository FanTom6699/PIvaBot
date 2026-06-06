# handlers/user_commands.py
from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.filters import Command

from database import Database
from settings import SettingsManager
from .beer_service import run_beer_attempt
from .common import (
    check_user_registered,
    get_chat_top_text,
    get_compact_profile_text,
    get_profile_keyboard,
    get_profile_text,
    get_rating_keyboard,
    get_rating_menu_text,
)

# --- ИНИЦИАЛИЗАЦИЯ --
user_commands_router = Router()

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


@user_commands_router.message(Command("top"))
@user_commands_router.message(Command("rating"))
async def cmd_rating(message: Message, bot: Bot, db: Database):
    # (Проверка регистрации в группе)
    if message.chat.type != 'private' and not await check_user_registered(message, bot, db):
        return

    if message.chat.type == 'private':
        user = message.from_user
        await db.add_user(user.id, user.first_name, user.last_name, user.username)
        await message.answer(
            get_rating_menu_text(),
            reply_markup=get_rating_keyboard(),
            parse_mode='HTML'
        )
    else:
        text = await get_chat_top_text(db, message.chat.id, message.from_user.id, message.chat.title)
        await message.answer(text, parse_mode='HTML')


@user_commands_router.message(Command("me"))
async def cmd_me(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    if message.chat.type != 'private' and not await check_user_registered(message, bot, db):
        return

    user = message.from_user
    await db.add_user(user.id, user.first_name, user.last_name, user.username)
    if message.chat.type == 'private':
        text = await get_profile_text(user.id, user.full_name, db, settings)
        await message.answer(text, reply_markup=get_profile_keyboard(user.id), parse_mode='HTML')
    else:
        text = await get_compact_profile_text(user.id, user.full_name, db, settings)
        await message.answer(text, parse_mode='HTML')


# --- ПРОФИЛЬ ---
@user_commands_router.message(Command("profile"))
async def cmd_profile(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    user = message.from_user
    await db.add_user(user.id, user.first_name, user.last_name, user.username)
    if message.chat.type == 'private':
        text = await get_profile_text(user.id, user.full_name, db, settings)
        await message.answer(text, reply_markup=get_profile_keyboard(user.id), parse_mode='HTML')
    else:
        text = await get_compact_profile_text(user.id, user.full_name, db, settings)
        await message.answer(text, parse_mode='HTML')

# handlers/give.py
import logging
from html import escape # ✅✅✅ ИСПРАВЛЕНИЕ: Импортируем "защиту" из 'html'

# ✅ ИЗМЕНЕНО: 'html' УБРАН из импорта aiogram
from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.filters import Command

from database import Database
from .common import check_user_registered
from .farm_config import FARM_ITEM_NAMES

# --- ИНИЦИАЛИЗАЦИЯ ---
give_router = Router()

ALLOWED_ITEMS = list(FARM_ITEM_NAMES.keys())

# --- ТЕКСТ "ПОМОЩИ" (Твой План) ---
GIVE_HELP_TEXT = (
    "⛔ <b>Ошибка!</b> Неправильный формат.\n\n"
    "<b>Помощь по передаче: <code>/кинуть</code></b>\n\n"
    "<b>Формат:</b> <code>/кинуть &lt;ресурс&gt; &lt;кол-во&gt; [цель]</code>\n\n"
    "<b>[Цель]</b> (необязательно, если отвечаешь):\n"
    "• <i>Ответ</i> (Reply) на сообщение\n"
    "• <code>@username</code>\n"
    "• <code>User ID</code>\n\n"
    "<b>&lt;Ресурсы&gt;:</b>\n"
    "• <code>зерно</code> (🌾 Урожай)\n"
    "• <code>хмель</code> (🌱 Урожай)\n"
    "• <code>семя_зерна</code> (🌾 Семена)\n"
    "• <code>семя_хмеля</code> (🌱 Семена)"
)

# --- ХЭНДЛЕР ---
@give_router.message(Command("кинуть", prefix="/!")) 
async def cmd_give_item(message: Message, bot: Bot, db: Database):
    
    if not await check_user_registered(message, bot, db):
        return

    sender = message.from_user
    args = message.text.split()

    # --- ПАРСИНГ ---
    item_id: str = ""
    quantity: int = 0
    target_user_id: int = 0
    target_user_name: str = ""
    
    if len(args) < 3:
        await message.reply(GIVE_HELP_TEXT)
        return

    item_id = args[1].lower()
    if item_id not in ALLOWED_ITEMS:
        # ✅✅✅ ИСПРАВЛЕНИЕ: Используем escape()
        await message.reply(f"⛔ <b>Ошибка!</b>\nНеизвестный ресурс: '<code>{escape(item_id)}</code>'.\n\n" + GIVE_HELP_TEXT)
        return
        
    item_name = FARM_ITEM_NAMES.get(item_id, item_id)

    if not args[2].isdigit() or int(args[2]) <= 0:
         # ✅✅✅ ИСПРАВЛЕНИЕ: Используем escape()
        await message.reply(f"⛔ <b>Ошибка!</b>\nКоличество '<code>{escape(args[2])}</code>' должно быть положительным числом.\n\n" + GIVE_HELP_TEXT)
        return
    
    quantity = int(args[2])

    # --- ПОИСК "ЦЕЛИ" ---
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
        if target_user.is_bot:
            await message.reply("⛔ Нельзя передавать ресурсы ботам.")
            return
        if target_user.id == sender.id:
            await message.reply("⛔ Нельзя передать ресурсы самому себе.")
            return
            
        target_user_id = target_user.id
        target_user_name = target_user.full_name

    elif len(args) >= 4:
        target_str = args[3]
        
        if target_str.startswith('@'):
            username = target_str[1:]
            if sender.username and (username.lower() == sender.username.lower()):
                 await message.reply("⛔ Нельзя передать ресурсы самому себе.")
                 return
                 
            target_data = await db.get_user_by_username(username)
            if not target_data:
                 # ✅✅✅ ИСПРАВЛЕНИЕ: Используем escape()
                await message.reply(f"⛔ <b>Ошибка!</b>\nНе могу найти игрока с <code>@{escape(username)}</code> в базе данных.")
                return
            target_user_id, target_user_name = target_data
        
        elif target_str.isdigit():
            user_id_int = int(target_str)
            if user_id_int == sender.id:
                 await message.reply("⛔ Нельзя передать ресурсы самому себе.")
                 return
                 
            target_data = await db.get_user_by_id(user_id_int)
            if not target_data:
                await message.reply(f"⛔ <b>Ошибка!</b>\nНе могу найти игрока с ID <code>{user_id_int}</code> в базе данных.")
                return
            target_user_id, target_user_name = target_data
            
        else:
            await message.reply(GIVE_HELP_TEXT)
            return
    
    else:
        await message.reply(GIVE_HELP_TEXT)
        return

    # --- ПРОВЕРКА БАЛАНСА ---
    sender_inventory = await db.get_user_inventory(sender.id)
    if sender_inventory.get(item_id, 0) < quantity:
        await message.reply(f"⛔ <b>Недостаточно!</b>\nУ тебя {sender_inventory.get(item_id, 0)} {item_name}, а ты пытаешься кинуть {quantity}.")
        return

    # --- ПЕРЕДАЧА ---
    try:
        success_remove = await db.modify_inventory(sender.id, item_id, -quantity)
        
        if not success_remove:
             await message.reply(f"⛔ <b>Недостаточно!</b> (Ошибка при списании)")
             return
        
        await db.modify_inventory(target_user_id, item_id, quantity)

    except Exception as e:
        logging.error(f"Критическая ошибка при передаче /кинуть (с {sender.id} на {target_user_id}): {e}")
        await db.modify_inventory(sender.id, item_id, quantity)
        await message.reply("⛔ <b>Критическая Ошибка!</b>\nПроизошла ошибка базы данных. Ресурсы возвращены тебе.")
        return

    # --- УСПЕХ ---
    await message.reply(
        # ✅✅✅ ИСПРАВЛЕНИЕ: Используем escape()
        f"✅ <b>Передача Успешна!</b>\n\n"
        f"<i>{escape(sender.full_name)}</i> передал {quantity} {item_name} игроку <i>{escape(target_user_name)}</i>!"
    )

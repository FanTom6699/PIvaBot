# handlers/admin.py
import asyncio
import os
from contextlib import suppress
from html import escape
import logging

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import Command, Filter, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

import config
from database import Database
from settings import SettingsManager

# --- ИНИЦИАЛИЗАЦИЯ ---
admin_router = Router()

# --- FSM СОСТОЯНИЯ ---
class AdminStates(StatesGroup):
    broadcast_message = State()
    give_beer_user = State()
    give_beer_amount = State()
    waiting_for_setting_value = State()

# --- ФИЛЬТРЫ ---
class IsAdmin(Filter):
    async def __call__(self, message: Message | CallbackQuery) -> bool:
        return message.from_user.id == config.ADMIN_ID

# --- CALLBACKDATA ФАБРИКИ ---
class AdminCallbackData(CallbackData, prefix="admin"):
    action: str

class AdminSettingsCallbackData(CallbackData, prefix="admin_set"):
    setting_key: str

# --- Вспомогательные функции для меню ---

async def get_main_admin_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="📢 Рассылка", callback_data=AdminCallbackData(action="broadcast").pack())],
        [InlineKeyboardButton(text="🍺 Выдать рейтинг", callback_data=AdminCallbackData(action="give_beer").pack())],
        [InlineKeyboardButton(text="⚙️ Настройки игры", callback_data=AdminCallbackData(action="settings").pack())],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data=AdminCallbackData(action="close").pack())]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def get_settings_menu(settings: SettingsManager) -> (str, InlineKeyboardMarkup):
    text = "<b>⚙️ Настройки игры:</b>\n\n"
    
    # Общие настройки
    text += "<b>Общие:</b>\n"
    text += settings.get_common_settings_text()
    
    kb = []
    # Генерируем кнопки для каждого ключа настроек
    all_settings = await settings.get_all_settings_dict()
    
    # Сортируем для удобства, разбиваем на строки по 2
    sorted_keys = sorted(all_settings.keys())
    row = []
    for key in sorted_keys:
        # Сокращаем длинные названия для кнопок
        btn_text = key.replace("mafia_", "M_")
        row.append(InlineKeyboardButton(
            text=f"{btn_text} ({all_settings[key]})", 
            callback_data=AdminSettingsCallbackData(setting_key=key).pack()
        ))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row: kb.append(row)
    
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=AdminCallbackData(action="main").pack())])
    return text, InlineKeyboardMarkup(inline_keyboard=kb)

# --- ХЭНДЛЕРЫ ---

@admin_router.message(Command("admin"), IsAdmin())
async def cmd_admin(message: Message):
    await message.answer("👋 <b>Админ-панель</b>", reply_markup=await get_main_admin_keyboard(), parse_mode='HTML')

# --- ✅ НОВАЯ КОМАНДА: СКАЧАТЬ БД ---
@admin_router.message(Command("get_db"), IsAdmin())
async def cmd_download_db(message: Message):
    # Пути для проверки (Render Disk vs Local)
    paths_to_check = [
        '/data/bot_database.db',  # Путь на Render (Disk)
        'bot_database.db'         # Локальный путь
    ]
    
    file_path = None
    for path in paths_to_check:
        if os.path.exists(path):
            file_path = path
            break
    
    if file_path:
        await message.answer("📂 Загружаю базу данных...")
        try:
            # Отправляем файл
            db_file = FSInputFile(file_path)
            await message.answer_document(db_file, caption=f"📦 Бэкап базы данных\nПуть: {file_path}")
        except Exception as e:
            await message.answer(f"⚠️ Ошибка при отправке файла: {e}")
    else:
        await message.answer("⛔ Файл базы данных не найден!\nЯ искал в: /data/bot_database.db и bot_database.db")


@admin_router.message(Command("getid"), IsAdmin())
async def cmd_get_media_id(message: Message):
    target = message.reply_to_message or message
    lines = ["<b>ID из сообщения</b>"]

    if target.sticker:
        sticker = target.sticker
        lines.extend([
            "",
            "<b>Стикер</b>",
            f"file_id:\n<code>{escape(sticker.file_id)}</code>",
            f"file_unique_id:\n<code>{escape(sticker.file_unique_id)}</code>",
            f"type: <code>{escape(str(sticker.type))}</code>",
        ])
        if sticker.emoji:
            lines.append(f"emoji: {escape(sticker.emoji)}")
        if sticker.set_name:
            lines.append(f"set_name: <code>{escape(sticker.set_name)}</code>")
        custom_emoji_id = getattr(sticker, "custom_emoji_id", None)
        if custom_emoji_id:
            lines.append(f"custom_emoji_id:\n<code>{escape(custom_emoji_id)}</code>")

    entities = list(target.entities or []) + list(target.caption_entities or [])
    custom_emoji_entities = [
        entity for entity in entities
        if entity.type == "custom_emoji" and getattr(entity, "custom_emoji_id", None)
    ]
    if custom_emoji_entities:
        lines.extend(["", "<b>Кастомные эмодзи</b>"])
        seen = set()
        for index, entity in enumerate(custom_emoji_entities, start=1):
            custom_emoji_id = entity.custom_emoji_id
            if custom_emoji_id in seen:
                continue
            seen.add(custom_emoji_id)
            lines.append(f"{index}. <code>{escape(custom_emoji_id)}</code>")

    if len(lines) == 1:
        lines.extend([
            "",
            "Ответь командой <code>/getid</code> на сообщение со стикером или кастомным эмодзи.",
        ])

    await message.answer("\n".join(lines), parse_mode="HTML")

# --- Callbacks: Главное меню ---

@admin_router.callback_query(AdminCallbackData.filter(F.action == "main"), IsAdmin())
async def cq_admin_main(callback: CallbackQuery):
    await callback.message.edit_text("👋 <b>Админ-панель</b>", reply_markup=await get_main_admin_keyboard(), parse_mode='HTML')
    await callback.answer()

@admin_router.callback_query(AdminCallbackData.filter(F.action == "close"), IsAdmin())
async def cq_admin_close(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

# --- Callbacks: Рассылка ---

@admin_router.callback_query(AdminCallbackData.filter(F.action == "broadcast"), IsAdmin())
async def cq_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("📢 Введите сообщение для рассылки (поддерживается HTML, фото/видео):")
    await state.set_state(AdminStates.broadcast_message)
    await callback.answer()

@admin_router.message(AdminStates.broadcast_message, IsAdmin())
async def process_broadcast(message: Message, state: FSMContext, bot: Bot, db: Database):
    users_count = 0
    errors_count = 0

    try:
        users = await db.get_all_users_ids()

        status_msg = await message.answer(f"⏳ Начинаю рассылку на {len(users)} пользователей...")

        for user_id in users:
            try:
                await message.copy_to(chat_id=user_id)
                users_count += 1
                await asyncio.sleep(0.05) # Избегаем флуд-лимитов
            except Exception:
                errors_count += 1

        await status_msg.edit_text(f"✅ Рассылка завершена!\nОтправлено: {users_count}\nОшибок: {errors_count}")

    except Exception as e:
        await message.answer(f"Ошибка БД: {e}")

    await state.clear()

# --- Callbacks: Выдача пива ---

@admin_router.callback_query(AdminCallbackData.filter(F.action == "give_beer"), IsAdmin())
async def cq_admin_give_beer(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("👤 Введите ID пользователя или перешлите его сообщение:")
    await state.set_state(AdminStates.give_beer_user)
    await callback.answer()

@admin_router.message(AdminStates.give_beer_user, IsAdmin())
async def process_give_beer_user(message: Message, state: FSMContext):
    user_id = None
    if message.forward_from:
        user_id = message.forward_from.id
    elif message.text.isdigit():
        user_id = int(message.text)
    
    if not user_id:
        await message.answer("⛔ Некорректный ID. Попробуйте снова.")
        return

    await state.update_data(target_user_id=user_id)
    await message.answer(f"🍺 Выбран User ID: <code>{user_id}</code>.\nВведите сумму (можно с минусом):", parse_mode='HTML')
    await state.set_state(AdminStates.give_beer_amount)

@admin_router.message(AdminStates.give_beer_amount, IsAdmin())
async def process_give_beer_amount(message: Message, state: FSMContext, db: Database):
    try:
        amount = int(message.text)
        data = await state.get_data()
        target_id = data['target_user_id']
        
        new_balance = await db.change_rating(target_id, amount)
        await message.answer(f"✅ Баланс пользователя <code>{target_id}</code> изменен на {amount}.\nТекущий: {new_balance} 🍺", parse_mode='HTML')
        await state.clear()
    except ValueError:
        await message.answer("⛔ Введите целое число.")

# --- Callbacks: Настройки (Settings) ---

@admin_router.callback_query(AdminCallbackData.filter(F.action == "settings"), IsAdmin())
async def cq_admin_settings(callback: CallbackQuery, settings: SettingsManager):
    text, kb = await get_settings_menu(settings)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=kb, parse_mode='HTML')
    await callback.answer()

@admin_router.callback_query(AdminSettingsCallbackData.filter(), IsAdmin())
async def cq_admin_edit_setting(callback: CallbackQuery, callback_data: AdminSettingsCallbackData, state: FSMContext):
    key = callback_data.setting_key
    await state.update_data(setting_key=key)
    await callback.message.answer(f"✏️ Введите новое значение для <b>{key}</b> (целое число):", parse_mode='HTML')
    await state.set_state(AdminStates.waiting_for_setting_value)
    await callback.answer()

@admin_router.message(AdminStates.waiting_for_setting_value, IsAdmin())
async def process_setting_value(message: Message, state: FSMContext, db: Database, settings: SettingsManager):
    if not message.text.isdigit():
        await message.answer("⛔ Значение должно быть числом!")
        return
        
    value = int(message.text)
    data = await state.get_data()
    key = data['setting_key']
    
    await db.update_setting(key, value)
    await settings.reload_setting(db, key)
    
    await message.answer(f"✅ Настройка <b>{key}</b> обновлена до <b>{value}</b>!", parse_mode='HTML')
    await state.clear()
    
    # Возвращаем меню
    text, kb = await get_settings_menu(settings)
    await message.answer(text, reply_markup=kb, parse_mode='HTML')

# --- КОМАНДЫ ДЛЯ ИЗМЕНЕНИЯ НАСТРОЕК (БЫСТРЫЕ) ---
@admin_router.message(Command("set"), IsAdmin())
async def cmd_set_setting(message: Message, db: Database, settings: SettingsManager):
    args = message.text.split()
    if len(args) != 3:
        await message.reply("Использование: <code>/set <ключ> <значение></code>\n"
                            "Пример: <code>/set beer_cooldown 3600</code>\n\n"
                            "Доступные ключи:\n"
                            "<code>beer_cooldown, jackpot_chance, roulette_cooldown, "
                            "roulette_min_bet, roulette_max_bet, ladder_min_bet, ladder_max_bet</code>",
                            parse_mode='HTML')
        return

    key, value = args[1], args[2]

    if not hasattr(settings, key):
        await message.reply(f"Ошибка: Неизвестный ключ настройки '<code>{key}</code>'.")
        return
        
    if not value.isdigit():
        await message.reply("Ошибка: Значение должно быть целым числом.")
        return
        
    int_value = int(value)
    
    try:
        await db.update_setting(key, int_value)
        await settings.reload_setting(db, key)
        await message.answer(f"✅ Настройка '<code>{key}</code>' успешно обновлена на <code>{int_value}</code>.", parse_mode='HTML')
        
        text, keyboard = await get_settings_menu(settings)
        await message.answer(text, reply_markup=keyboard, parse_mode='HTML')
        
    except Exception as e:
        await message.reply(f"Ошибка БД: {e}")

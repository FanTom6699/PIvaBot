# handlers/farm.py
import asyncio
import logging
import random
from datetime import datetime, timedelta
from contextlib import suppress
from typing import Dict, Any, Optional
from html import escape 

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.exceptions import TelegramBadRequest

from database import Database
from .common import check_user_registered
from utils import format_time_delta

from .farm_config import (
    FARM_ITEM_NAMES, 
    BREWERY_RECIPE, 
    FIELD_UPGRADES, 
    BREWERY_UPGRADES, 
    get_level_data,
    SHOP_PRICES,
    CROP_CODE_TO_ID,
    CROP_SHORT,
    SEED_TO_PRODUCT_ID,
    FARM_ORDER_POOL
)

farm_router = Router()

# --- UI HELPERS (ТВОИ ФУНКЦИИ) ---
def ui_bar(pct: int, width: int = 10) -> str:
    pct = max(0, min(100, pct))
    fill = int(width * pct / 100)
    return f"[{'█' * fill}{'░' * (width - fill)}] {pct}%"

def rows(btns, per_row: int) -> list[list]:
    return [btns[i:i + per_row] for i in range(0, len(btns), per_row)]

def safe_name(map_: dict, key: str, fallback: str = "??") -> str:
    return map_.get(key, fallback)

def dash_title(user_name: str) -> str:
    return f"<b>🌾 Ферма: {escape(user_name)}</b>"

def back_btn_to_farm(user_id: int) -> list:
    # Используем исправленный FarmCallback
    return [InlineKeyboardButton(text="⬅️ Назад на Ферму", callback_data=FarmCallback(action="main_dashboard", owner_id=user_id).pack())]


def get_farm_help_text() -> str:
    return (
        "🌾 <b>Ферма</b>\n\n"
        "Ферма нужна, чтобы выращивать сырье, варить пиво и получать 🍺 рейтинг.\n\n"
        "<code>--- --- ---</code>\n"
        "<b>Основной цикл:</b>\n"
        "• Купи семена в <b>🏪 Магазине</b>.\n"
        "• Посади их на свободные грядки в <b>🌾 Поле</b>.\n"
        "• Дождись урожая и собери <b>🌾 зерно</b> или <b>🌱 хмель</b>.\n"
        "• Отправь сырье в <b>🏭 Пивоварню</b>.\n"
        "• Забери готовую партию и получи 🍺 рейтинг.\n\n"
        "<code>--- --- ---</code>\n"
        "<b>Разделы фермы:</b>\n"
        "• <b>🌾 Поле</b> - грядки, посадка и сбор урожая.\n"
        "• <b>🏭 Пивоварня</b> - варка пива из зерна и хмеля.\n"
        "• <b>📦 Склад</b> - твои семена и собранное сырье.\n"
        "• <b>📋 Доска заказов</b> - задания за награды.\n"
        "• <b>⭐ Улучшения</b> - больше грядок и сильнее пивоварня.\n"
        "• <b>🏪 Магазин</b> - покупка семян.\n\n"
        "<code>--- --- ---</code>\n"
        "<b>Советы:</b>\n"
        "• Не держи грядки пустыми, если есть семена.\n"
        "• Сначала следи за балансом зерна и хмеля.\n"
        "• Улучшения стоят 🍺, но быстрее окупаются.\n"
        "• Если что-то готово, ферма обычно подскажет это на главном экране."
    )


def format_order_reward(order: dict) -> str:
    if order['reward_type'] == 'beer':
        return f"+{order['reward_amount']} 🍺"
    if order['reward_type'] == 'item':
        item_name = FARM_ITEM_NAMES.get(order['reward_id'], order['reward_id'])
        return f"+{order['reward_amount']} {item_name}"
    return "Награда"


def get_order_items(order: dict) -> dict:
    if 'items' in order:
        return order['items']
    return {order['item_id']: order['item_amount']}


def can_complete_order(order: dict, inventory: dict) -> bool:
    return all(
        inventory.get(item_id, 0) >= amount
        for item_id, amount in get_order_items(order).items()
    )


def format_order_block(slot_id: int, order: dict, inventory: dict, is_completed: int) -> str:
    reward_text = format_order_reward(order)
    item_lines = []
    for item_id, needed in get_order_items(order).items():
        item_name = FARM_ITEM_NAMES.get(item_id, item_id)
        available = inventory.get(item_id, 0)
        progress = min(available, needed)
        item_lines.append(f"• <b>{progress}/{needed}</b> {item_name}")

    if is_completed:
        status = "✅ Выполнено"
    elif can_complete_order(order, inventory):
        status = "🟢 Можно сдать"
    else:
        status = "🔴 Не хватает"

    return (
        f"\n<b>{slot_id}. {order['text']}</b>\n"
        f"{status}\n"
        f"Нужно:\n" + "\n".join(item_lines) + "\n"
        f"Награда: <b>{reward_text}</b>\n"
    )

# --- ✅ CALLBACK DATA (РАЗДЕЛЕННЫЕ) ---

# 1. Обычные кнопки (чтобы не висли)
class FarmCallback(CallbackData, prefix="farm"):
    action: str 
    owner_id: int 

# 2. Заказы (отдельно, с доп. полями)
class OrderCallback(CallbackData, prefix="order"):
    action: str
    owner_id: int
    slot_id: int
    order_id: str

class PlotCallback(CallbackData, prefix="plot"):
    action: str 
    owner_id: int
    plot_num: int
    crop_id: Optional[str] = None 

class BreweryCallback(CallbackData, prefix="brew"):
    action: str 
    owner_id: int
    quantity: int = 0

class UpgradeCallback(CallbackData, prefix="upgrade"):
    action: str 
    owner_id: int


# --- RENDER: DASHBOARD (ВОЗВРАЩЕН ТВОЙ ДИЗАЙН) ---
async def get_farm_dashboard(user_id: int, user_name: str, db: Database) -> (str, InlineKeyboardMarkup):
    
    # Данные
    farm = await db.get_user_farm_data(user_id)
    rating = await db.get_user_beer_rating(user_id)
    inventory = await db.get_user_inventory(user_id)
    active_plots = await db.get_user_plots(user_id)
    now = datetime.now()

    # Поле
    field_lvl = farm.get('field_level', 1)
    field_stats = get_level_data(field_lvl, FIELD_UPGRADES)
    max_plots = field_stats['plots']

    ready_plots_count = 0
    growing_plots_count = 0
    min_ready_time = None 

    for plot_num, crop_id, ready_str in active_plots:
        if isinstance(ready_str, str):
            ready_dt = datetime.fromisoformat(ready_str)
            if now >= ready_dt:
                ready_plots_count += 1
            else:
                growing_plots_count += 1
                if min_ready_time is None or ready_dt < min_ready_time:
                    min_ready_time = ready_dt
            
    empty_plots_count = max_plots - ready_plots_count - growing_plots_count
    
    # Пивоварня
    brew_lvl = farm.get('brewery_level', 1)
    brew_stats = get_level_data(brew_lvl, BREWERY_UPGRADES)
    
    brewery_status_text = ""
    brew_upgrade_timer = farm.get('brewery_upgrade_timer_end')
    batch_timer = farm.get('brewery_batch_timer_end') 

    if brew_upgrade_timer and now < brew_upgrade_timer:
        left = format_time_delta(brew_upgrade_timer - now)
        brewery_status_text = f"<i>(⚠ Закрыто на улучшение... ⏳ {left})</i>"
    elif batch_timer: 
        if now >= batch_timer:
            brewery_status_text = "<b>(🏆 ГОТОВО! Забери награду!)</b>"
        else:
            left = format_time_delta(batch_timer - now)
            brewery_status_text = f"<i>(Варка... ⏳ {left})</i>"
    else:
        brewery_status_text = "<i>(Готова к варке)</i>"

    # Советы (Твоя логика)
    advice = "✨ Совет: Ферма в порядке. Так держать!"
    
    field_upgrade_timer_end = farm.get('field_upgrade_timer_end')
    brewery_upgrade_timer_end = farm.get('brewery_upgrade_timer_end')
    
    can_upgrade_field = (not field_upgrade_timer_end or now >= field_upgrade_timer_end)
    can_upgrade_brewery = (not brewery_upgrade_timer_end or now >= brewery_upgrade_timer_end)

    if not field_stats['max_level'] and rating >= field_stats.get('next_cost', 999999) and can_upgrade_field:
        advice = "✨ Совет: У тебя хватает 🍺 на улучшение [🌾 Поля]!"
    elif not brew_stats['max_level'] and rating >= brew_stats.get('next_cost', 999999) and can_upgrade_brewery:
        advice = "✨ Совет: У тебя хватает 🍺 на улучшение [🏭 Пивоварни]!"
    elif (not batch_timer and not brew_upgrade_timer and 
          inventory['зерно'] >= BREWERY_RECIPE['зерно'] and
          inventory['хмель'] >= BREWERY_RECIPE['хмель']):
        advice = "✨ Совет: [🏭 Пивоварня] простаивает! Пора варить 🍺!"
    elif empty_plots_count > 0 and (inventory['семя_зерна'] > 0 or inventory['семя_хмеля'] > 0):
        advice = "✨ Совет: У тебя есть пустые грядки и семена. Пора сажать!"

    # --- ТЕКСТ (Твой стиль) ---
    text = (
        f"{dash_title(user_name)}\n\n"
        
        f"<b>📊 Статистика:</b>\n"
        f"• 🍺 Рейтинг: <b>{rating}</b>\n"
        f"• 🌾 Зерно:    <b>{inventory['зерно']}</b>\n"
        f"• 🌱 Хмель:    <b>{inventory['хмель']}</b>\n"
        f"<code>--- --- ---</code>\n"
        
        f"<b>🌱 Поле (Ур. {field_lvl}):</b>\n"
        f"• ✅ Готово к сбору: <b>{ready_plots_count}</b> грядок\n"
        f"• ⏳ Зреет: <b>{growing_plots_count}</b> грядок\n"
        f"• 🟦 Пусто: <b>{empty_plots_count}</b> грядок\n"
    )
    
    if min_ready_time:
        time_left_str = format_time_delta(min_ready_time - now)
        text += f"<i>(Ближайший урожай: {time_left_str})</i>\n"
    elif ready_plots_count > 0:
        text += "<i>(Пора собирать урожай!)</i>\n"
    else:
        text += "<i>(Все грядки свободны)</i>\n"

    text += "\n"
    
    text += f"<b>🏭 Пивоварня (Ур. {brew_lvl}):</b>\n"
    text += f"• {brewery_status_text}\n"
    
    text += f"<code>--- --- ---</code>\n"
    text += f"{advice}\n"

    # --- КНОПКИ ---
    kb = []
    
    # Кнопка Поля
    if field_upgrade_timer_end and now < field_upgrade_timer_end:
        kb.append([InlineKeyboardButton(
            text="🌾 Поле (⚠ закрыто на улучшение)", 
            callback_data=FarmCallback(action="show_upgrade_time", owner_id=user_id).pack()
        )])
    else:
        field_btn_text = "🌾 Моё Поле (СОБРАТЬ!)" if ready_plots_count > 0 else "🌾 Моё Поле (Грядки)"
        kb.append([InlineKeyboardButton(text=field_btn_text, callback_data=FarmCallback(action="view_plots", owner_id=user_id).pack())])

    # Кнопка Пивоварни
    if brew_upgrade_timer and now < brew_upgrade_timer:
        kb.append([InlineKeyboardButton(
            text=f"🏭 Пивоварня (⚠ закрыто на улучшение)", 
            callback_data=FarmCallback(action="show_upgrade_time", owner_id=user_id).pack()
        )])
    elif batch_timer: 
        if now >= batch_timer:
            reward = brew_stats.get('reward', 0)
            total = reward * farm.get('brewery_batch_size', 0)
            kb.append([InlineKeyboardButton(text=f"🏆 Забрать +{total} 🍺", callback_data=BreweryCallback(action="collect", owner_id=user_id).pack())])
        else:
            kb.append([InlineKeyboardButton(
                text=f"🏭 Пивоварня (варит...)", 
                callback_data=FarmCallback(action="show_brew_time", owner_id=user_id).pack()
            )])
    else:
        kb.append([InlineKeyboardButton(text="🏭 Пивоварня (Меню)", callback_data=BreweryCallback(action="brew_menu", owner_id=user_id).pack())])

    # Остальные кнопки 
    kb_buttons = [
        InlineKeyboardButton(text="📋 Доска Заказов", callback_data=FarmCallback(action="orders_menu", owner_id=user_id).pack()),
        
        InlineKeyboardButton(text="📦 Склад",     callback_data=FarmCallback(action="inventory", owner_id=user_id).pack()),
        InlineKeyboardButton(text="⭐ Улучшения", callback_data=FarmCallback(action="upgrades",  owner_id=user_id).pack()),
        InlineKeyboardButton(text="🏪 Магазин",   callback_data=FarmCallback(action="shop",      owner_id=user_id).pack()),
        InlineKeyboardButton(text="❓ Как играть?", callback_data=FarmCallback(action="show_help", owner_id=user_id).pack())
    ]
    kb += rows(kb_buttons, per_row=2)
    kb.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:home")])

    return text, InlineKeyboardMarkup(inline_keyboard=kb)


# --- RENDER: PLOTS DASHBOARD (ВОЗВРАЩЕН ТВОЙ ДИЗАЙН) ---
async def get_plots_dashboard(user_id: int, db: Database) -> (str, InlineKeyboardMarkup):
    farm = await db.get_user_farm_data(user_id)
    now = datetime.now()

    lvl = farm.get('field_level', 1)
    stats = get_level_data(lvl, FIELD_UPGRADES)
    max_plots = stats['plots']
    
    g_time = stats.get('grow_time_min', {}).get('зерно', '??')
    h_time = stats.get('grow_time_min', {}).get('хмель', '??')
    
    text = (
        f"<b>🌱 Поле (Ур. {lvl})</b>\n"
        f"<i>Грядок: {stats.get('plots', '??')}, Шанс x2: {stats.get('chance_x2', '??')}%</i>\n"
        f"<i>Время роста: 🌾 {g_time}м / 🌱 {h_time}м</i>\n\n"
        f"Нажми на <b>Пусто</b>, чтобы посадить.\n"
    )

    raw = await db.get_user_plots(user_id)
    active = {}
    for plot_num, crop_id, ready_str in raw:
        if isinstance(ready_str, str):
            active[plot_num] = (crop_id, datetime.fromisoformat(ready_str))

    per_row = 2 if max_plots <= 4 else 3
    plot_btns = []
    for i in range(1, max_plots + 1):
        if i in active:
            seed_id, ready = active[i]
            
            product_id = SEED_TO_PRODUCT_ID.get(seed_id, '??')
            crop_name = safe_name(CROP_SHORT, product_id, "??")
            
            if now >= ready:
                txt = f"✅ {crop_name} (Собрать)"
                cb  = PlotCallback(action="harvest", owner_id=user_id, plot_num=i).pack()
            else:
                left = format_time_delta(ready - now)
                txt = f"⏳ {crop_name} ({left})"
                cb  = PlotCallback(action="show_time", owner_id=user_id, plot_num=i).pack()
                
        else:
            txt = f"🟦 Грядка {i} (Пусто)"
            cb  = PlotCallback(action="plant_menu", owner_id=user_id, plot_num=i).pack()
        plot_btns.append(InlineKeyboardButton(text=txt, callback_data=cb))

    kb = rows(plot_btns, per_row=per_row)
    kb.append(back_btn_to_farm(user_id))

    return text, InlineKeyboardMarkup(inline_keyboard=kb)


# --- HANDLERS (С НУЖНЫМИ ПРОВЕРКАМИ) ---

async def check_owner(callback: CallbackQuery, owner_id: int) -> bool:
    if callback.from_user.id != owner_id:
        await callback.answer("⛔ Это не твоя ферма!", show_alert=True)
        return False
    return True

@farm_router.message(Command("farm"))
async def cmd_farm(message: Message, bot: Bot, db: Database):
    user_id = message.from_user.id
    if not await check_user_registered(message, bot, db): return
    try:
        text, keyboard = await get_farm_dashboard(user_id, message.from_user.full_name, db)
        await message.answer(text, reply_markup=keyboard)
    except Exception as e:
        logging.error(f"Critical error in cmd_farm: {e}", exc_info=True)
        await message.answer("⛔ Ошибка при загрузке Фермы!")

@farm_router.callback_query(FarmCallback.filter(F.action == "main_dashboard"))
async def cq_farm_main_dashboard(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    try:
        text, keyboard = await get_farm_dashboard(callback.from_user.id, callback.from_user.full_name, db)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        logging.error(f"Dash error: {e}")
    await callback.answer()

@farm_router.callback_query(FarmCallback.filter(F.action == "view_plots"))
async def cq_farm_view_plots(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    try:
        text, keyboard = await get_plots_dashboard(callback.from_user.id, db)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        logging.error(f"Plots error: {e}")
    await callback.answer()

# --- МАГАЗИН (ПЕРЕАДРЕСАЦИЯ) ---
@farm_router.callback_query(FarmCallback.filter(F.action == "shop"))
async def cq_farm_go_to_shop(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    from .shop import get_shop_menu 
    if not await check_owner(callback, callback_data.owner_id): return
    try:
        text, keyboard = await get_shop_menu(callback.from_user.id, db, callback_data.owner_id)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        logging.error(f"Shop error: {e}")
        await callback.answer("Ошибка магазина", show_alert=True)
    await callback.answer()

# --- СКЛАД ---
@farm_router.callback_query(FarmCallback.filter(F.action == "inventory"))
async def cq_farm_inventory(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    try:
        user_id = callback.from_user.id
        inv = await db.get_user_inventory(user_id)
        text = (
            f"<b>📦 Мой Склад</b>\n\n"
            f"<b>Урожай:</b>\n"
            f"• {FARM_ITEM_NAMES['зерно']}: <b>{inv['зерно']}</b>\n"
            f"• {FARM_ITEM_NAMES['хмель']}: <b>{inv['хмель']}</b>\n\n"
            f"<b>Семена:</b>\n"
            f"• {FARM_ITEM_NAMES['семя_зерна']}: <b>{inv['семя_зерна']}</b>\n"
            f"• {FARM_ITEM_NAMES['семя_хмеля']}: <b>{inv['семя_хмеля']}</b>"
        )
        kb = [back_btn_to_farm(user_id)]
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except Exception as e:
        logging.error(f"Inv error: {e}")
    await callback.answer()

# --- ORDERS (ИСПОЛЬЗУЕМ OrderCallback) ---
@farm_router.callback_query(FarmCallback.filter(F.action == "orders_menu"))
async def cq_farm_orders_menu(callback: CallbackQuery, db: Database, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data.owner_id): return
    try:
        user_id = callback.from_user.id
        await db.check_and_reset_orders(user_id)
        orders = await db.get_user_orders(user_id)
        inventory = await db.get_user_inventory(user_id)
        
        text = (
            "📋 <b>Доска заказов</b>\n\n"
            "Бармен оставил поручения на сегодня.\n"
            "Заказы обновляются раз в 24 часа.\n\n"
            "<code>--- --- ---</code>\n"
        )
        buttons = []

        for slot_id, order_id, is_completed in orders:
            if order_id not in FARM_ORDER_POOL: continue
            order = FARM_ORDER_POOL[order_id]
            reward_text = format_order_reward(order)
            text += format_order_block(slot_id, order, inventory, is_completed)

            if not is_completed:
                if can_complete_order(order, inventory):
                    cb = OrderCallback(action="complete", owner_id=user_id, slot_id=slot_id, order_id=order_id).pack()
                    buttons.append(InlineKeyboardButton(text=f"✅ Сдать {slot_id} ({reward_text})", callback_data=cb))

        kb_rows = [[btn] for btn in buttons]
        kb_rows.append(back_btn_to_farm(user_id))
        
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    except Exception as e:
        logging.error(f"Orders error: {e}")
    await callback.answer()

@farm_router.callback_query(OrderCallback.filter(F.action == "complete"))
async def cq_farm_order_complete(callback: CallbackQuery, db: Database, callback_data: OrderCallback):
    if not await check_owner(callback, callback_data.owner_id): return
    try:
        user_id = callback.from_user.id
        order = FARM_ORDER_POOL.get(callback_data.order_id)
        if not order: return await callback.answer("Заказ устарел", show_alert=True)

        inv = await db.get_user_inventory(user_id)
        if not can_complete_order(order, inv):
            return await callback.answer("Не хватает ресурсов!", show_alert=True)

        if not await db.complete_order(user_id, callback_data.slot_id):
            return await callback.answer("Уже выполнено!", show_alert=True)

        for item_id, amount in get_order_items(order).items():
            await db.modify_inventory(user_id, item_id, -amount)
        
        msg = ""
        if order['reward_type'] == 'beer':
            await db.change_rating(user_id, order['reward_amount'])
            msg = format_order_reward(order)
        elif order['reward_type'] == 'item':
            await db.modify_inventory(user_id, order['reward_id'], order['reward_amount'])
            msg = format_order_reward(order)

        await callback.answer(f"Заказ выполнен! {msg}", show_alert=True)
        await cq_farm_orders_menu(callback, db, FarmCallback(action="orders_menu", owner_id=user_id))
    except Exception as e:
        logging.error(f"Order complete error: {e}")
        await callback.answer("Ошибка выполнения", show_alert=True)

# --- ДЕЙСТВИЯ (Остальное без изменений логики, только callback'и) ---
@farm_router.callback_query(PlotCallback.filter(F.action == "plant_menu"))
async def cq_plot_plant_menu(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    user_id = callback.from_user.id
    inv = await db.get_user_inventory(user_id)
    
    text = f"<b>🌱 Посадка — Грядка {callback_data.plot_num}</b>\nНа складе:\n🌾 {inv['семя_зерна']} | 🌱 {inv['семя_хмеля']}"
    btns = []
    if inv['семя_зерна'] > 0:
        btns.append(InlineKeyboardButton(text="Посадить 🌾 Зерно", callback_data=PlotCallback(action="plant_do", owner_id=user_id, plot_num=callback_data.plot_num, crop_id="g").pack()))
    if inv['семя_хмеля'] > 0:
        btns.append(InlineKeyboardButton(text="Посадить 🌱 Хмель", callback_data=PlotCallback(action="plant_do", owner_id=user_id, plot_num=callback_data.plot_num, crop_id="h").pack()))
    
    rows_kb = rows(btns, 1)
    if not btns:
        text += "\n\n⛔ Нет семян! Купите в магазине."
        rows_kb.append([InlineKeyboardButton(text="🏪 В Магазин", callback_data=FarmCallback(action="shop", owner_id=user_id).pack())])
    
    rows_kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=FarmCallback(action="view_plots", owner_id=user_id).pack())])
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows_kb))
    await callback.answer()

@farm_router.callback_query(PlotCallback.filter(F.action == "plant_do"))
async def cq_plot_plant_do(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    user_id = callback.from_user.id
    crop_id = CROP_CODE_TO_ID.get(callback_data.crop_id)
    
    if await db.modify_inventory(user_id, crop_id, -1):
        farm = await db.get_user_farm_data(user_id)
        stats = get_level_data(farm.get('field_level', 1), FIELD_UPGRADES)
        prod_id = SEED_TO_PRODUCT_ID[crop_id]
        minutes = stats['grow_time_min'][prod_id]
        ready = datetime.now() + timedelta(minutes=minutes)
        
        await db.plant_crop(user_id, callback_data.plot_num, crop_id, ready)
        await callback.answer(f"Посажено! Ждать {minutes} мин.")
        await cq_farm_view_plots(callback, FarmCallback(action="view_plots", owner_id=user_id), db)
    else:
        await callback.answer("Нет семян!", show_alert=True)

@farm_router.callback_query(PlotCallback.filter(F.action == "harvest"))
async def cq_plot_harvest(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    seed = await db.harvest_plot(callback.from_user.id, callback_data.plot_num)
    if seed:
        prod = SEED_TO_PRODUCT_ID[seed]
        await db.modify_inventory(callback.from_user.id, prod, 1)
        await callback.answer(f"Собрано: 1 {FARM_ITEM_NAMES[prod]}")
        await cq_farm_view_plots(callback, FarmCallback(action="view_plots", owner_id=callback.from_user.id), db)
    else:
        await callback.answer("Ошибка сбора", show_alert=True)

@farm_router.callback_query(PlotCallback.filter(F.action == "show_time"))
async def cq_plot_time(callback: CallbackQuery):
    await callback.answer("Еще растет...", show_alert=True)

# --- ПИВОВАРНЯ ---
@farm_router.callback_query(BreweryCallback.filter(F.action == "brew_menu"))
async def cq_brewery_menu(callback: CallbackQuery, callback_data: BreweryCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    uid = callback.from_user.id
    inv = await db.get_user_inventory(uid)
    text = f"🏭 <b>Пивоварня</b>\n\nНужно на 1 варку:\n🌾 {BREWERY_RECIPE['зерно']} Зерна\n🌱 {BREWERY_RECIPE['хмель']} Хмеля\n\nУ тебя:\n🌾 {inv['зерно']} | 🌱 {inv['хмель']}"
    
    can_brew = inv['зерно'] >= BREWERY_RECIPE['зерно'] and inv['хмель'] >= BREWERY_RECIPE['хмель']
    btns = []
    if can_brew:
        btns.append(InlineKeyboardButton(text="🔥 Варить (1)", callback_data=BreweryCallback(action="brew_do", owner_id=uid, quantity=1).pack()))
    
    kb = rows(btns, 1)
    kb.append(back_btn_to_farm(uid))
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@farm_router.callback_query(BreweryCallback.filter(F.action == "brew_do"))
async def cq_brewery_do(callback: CallbackQuery, callback_data: BreweryCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    uid = callback.from_user.id
    qty = callback_data.quantity
    
    if await db.modify_inventory(uid, 'зерно', -BREWERY_RECIPE['зерно']*qty) and \
       await db.modify_inventory(uid, 'хмель', -BREWERY_RECIPE['хмель']*qty):
           
        farm = await db.get_user_farm_data(uid)
        stats = get_level_data(farm.get('brewery_level', 1), BREWERY_UPGRADES)
        minutes = stats['brew_time_min']
        ready = datetime.now() + timedelta(minutes=minutes*qty)
        
        await db.start_brewing(uid, qty, ready)
        await callback.answer("Варка началась!")
        await cq_farm_main_dashboard(callback, FarmCallback(action="main_dashboard", owner_id=uid), db)
    else:
        await callback.answer("Ошибка ресурсов!", show_alert=True)

@farm_router.callback_query(BreweryCallback.filter(F.action == "collect"))
async def cq_brewery_collect(callback: CallbackQuery, callback_data: BreweryCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    uid = callback.from_user.id
    farm = await db.get_user_farm_data(uid)
    stats = get_level_data(farm.get('brewery_level', 1), BREWERY_UPGRADES)
    reward = stats['reward'] * farm.get('brewery_batch_size', 1)
    
    await db.collect_brewery(uid, reward)
    await callback.answer(f"Сварено! +{reward} 🍺")
    await cq_farm_main_dashboard(callback, FarmCallback(action="main_dashboard", owner_id=uid), db)

@farm_router.callback_query(FarmCallback.filter(F.action == "show_brew_time"))
async def cq_show_brew_time(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    farm = await db.get_user_farm_data(callback_data.owner_id)
    if farm.get('brewery_batch_timer_end'):
         left = format_time_delta(farm['brewery_batch_timer_end'] - datetime.now())
         await callback.answer(f"⏳ Варится... {left}", show_alert=True)
    else:
         await callback.answer("Не варится.")

@farm_router.callback_query(FarmCallback.filter(F.action == "show_upgrade_time"))
async def cq_show_upgrade_time(callback: CallbackQuery):
    await callback.answer("⏳ Идет стройка...", show_alert=True)


# --- УЛУЧШЕНИЯ ---
@farm_router.callback_query(FarmCallback.filter(F.action == "upgrades"))
async def cq_farm_upgrades(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    user_id = callback.from_user.id
    balance = await db.get_user_beer_rating(user_id)
    farm = await db.get_user_farm_data(user_id)
    
    text = f"<b>⭐ Улучшения</b>\n<i>Твой Рейтинг: {balance} 🍺</i>\n\n"
    buttons = []

    # Поле
    f_lvl = farm.get('field_level', 1)
    text += f"<b>🌱 Поле — Уровень {f_lvl}</b>\n"
    if farm.get('field_upgrade_timer_end'):
        text += "<i>(Строится...)</i>\n"
    else:
        f_next = get_level_data(f_lvl + 1, FIELD_UPGRADES)
        if f_next.get('max_level'):
            text += "<b>⭐ Макс. уровень!</b>\n"
        else:
             cost = f_next['cost']
             text += f"Цена: {cost} 🍺\n"
             if balance >= cost:
                 buttons.append([InlineKeyboardButton(text=f"⬆️ Улучшить Поле", callback_data=UpgradeCallback(action="buy_field", owner_id=user_id).pack())])
    
    text += "\n" # Разделитель
    
    # Пивоварня
    b_lvl = farm.get('brewery_level', 1)
    text += f"<b>🏭 Пивоварня — Уровень {b_lvl}</b>\n"
    if farm.get('brewery_upgrade_timer_end'):
        text += "<i>(Строится...)</i>\n"
    else:
        b_next = get_level_data(b_lvl + 1, BREWERY_UPGRADES)
        if b_next.get('max_level'):
             text += "<b>⭐ Макс. уровень!</b>\n"
        else:
             cost = b_next['cost']
             text += f"Цена: {cost} 🍺\n"
             if balance >= cost:
                 buttons.append([InlineKeyboardButton(text=f"⬆️ Улучшить Пивоварню", callback_data=UpgradeCallback(action="buy_brewery", owner_id=user_id).pack())])

    buttons.append(back_btn_to_farm(user_id))
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@farm_router.callback_query(UpgradeCallback.filter(F.action.in_({"buy_field", "buy_brewery"})))
async def cq_upgrade_confirm(callback: CallbackQuery, callback_data: UpgradeCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    b_type = "field" if callback_data.action == "buy_field" else "brewery"
    farm = await db.get_user_farm_data(callback.from_user.id)
    lvl = farm.get(f'{b_type}_level', 1)
    stats = get_level_data(lvl + 1, FIELD_UPGRADES if b_type == 'field' else BREWERY_UPGRADES)
    
    await db.start_upgrade(callback.from_user.id, b_type, datetime.now() + timedelta(hours=stats['time_h']), stats['cost'])
    await callback.answer("Стройка началась!")
    await cq_farm_main_dashboard(callback, FarmCallback(action="main_dashboard", owner_id=callback.from_user.id), db)

@farm_router.callback_query(FarmCallback.filter(F.action == "show_help"))
async def cq_farm_help(callback: CallbackQuery, callback_data: FarmCallback):
    text = get_farm_help_text()
    kb = [back_btn_to_farm(callback.from_user.id)]
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

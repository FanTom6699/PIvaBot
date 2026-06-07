# handlers/farm.py
import asyncio
import logging
import random
from datetime import datetime, timedelta
from contextlib import suppress
from typing import Dict, Any, Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.exceptions import TelegramBadRequest

from database import Database
from .common import check_user_registered, get_main_menu_keyboard, get_private_start_text
from .text_aliases import FARM_ALIASES, GroupTextAlias
from utils import answer_to_trigger, format_time_delta, mention_user

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
DIVIDER = "<code>--- --- ---</code>"

# --- UI HELPERS (ТВОИ ФУНКЦИИ) ---
def ui_bar(pct: int, width: int = 10) -> str:
    pct = max(0, min(100, pct))
    fill = int(width * pct / 100)
    return f"[{'█' * fill}{'░' * (width - fill)}] {pct}%"

def rows(btns, per_row: int) -> list[list]:
    return [btns[i:i + per_row] for i in range(0, len(btns), per_row)]

def safe_name(map_: dict, key: str, fallback: str = "??") -> str:
    return map_.get(key, fallback)

def dash_title(user_id: int, user_name: str) -> str:
    return f"<b>🌾 Ферма: {mention_user(user_id, user_name)}</b>"

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
async def get_farm_dashboard(user_id: int, user_name: str, db: Database, show_main_menu: bool = True) -> (str, InlineKeyboardMarkup):
    
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
        brewery_status_text = f"<i>Идет улучшение: {left}</i>"
    elif batch_timer:
        if now >= batch_timer:
            brewery_status_text = "<b>Партия готова. Забери награду.</b>"
        else:
            left = format_time_delta(batch_timer - now)
            brewery_status_text = f"<i>Варится: {left}</i>"
    else:
        brewery_status_text = "<i>Свободна для новой варки.</i>"

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

    recipe_grain = BREWERY_RECIPE['зерно']
    recipe_hops = BREWERY_RECIPE['хмель']
    missing_grain = max(0, recipe_grain - inventory['зерно'])
    missing_hops = max(0, recipe_hops - inventory['хмель'])

    text = (
        f"{dash_title(user_id, user_name)}\n\n"
        f"🍺 Рейтинг: <b>{rating}</b>\n"
        f"🌾 Зерно: <b>{inventory['зерно']}</b> / 🌱 Хмель: <b>{inventory['хмель']}</b>\n\n"
        f"{DIVIDER}\n"
        f"🌾 <b>Поле</b> · ур. <b>{field_lvl}</b>\n"
        f"Готово: <b>{ready_plots_count}</b> · Растет: <b>{growing_plots_count}</b> · Пусто: <b>{empty_plots_count}</b>\n"
    )
    
    if min_ready_time:
        time_left_str = format_time_delta(min_ready_time - now)
        text += f"<i>Ближайший урожай: {time_left_str}</i>\n"
    elif ready_plots_count > 0:
        text += "<i>Пора собирать урожай.</i>\n"
    else:
        text += "<i>Грядки ждут посадки.</i>\n"

    text += "\n"
    
    text += f"🏭 <b>Пивоварня</b> · ур. <b>{brew_lvl}</b>\n"
    text += f"{brewery_status_text}\n"
    if not batch_timer and not brew_upgrade_timer and (missing_grain or missing_hops):
        missing_parts = []
        if missing_grain:
            missing_parts.append(f"🌾 {missing_grain}")
        if missing_hops:
            missing_parts.append(f"🌱 {missing_hops}")
        text += f"<i>Для варки не хватает: {' / '.join(missing_parts)}</i>\n"

    text += f"\n{DIVIDER}\n"
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
        field_btn_text = "🌾 Поле · собрать" if ready_plots_count > 0 else "🌾 Поле"
        kb.append([InlineKeyboardButton(text=field_btn_text, callback_data=FarmCallback(action="view_plots", owner_id=user_id).pack())])

    # Кнопка Пивоварни
    if brew_upgrade_timer and now < brew_upgrade_timer:
        kb.append([InlineKeyboardButton(
            text="🏭 Пивоварня (⚠ улучшение)",
            callback_data=FarmCallback(action="show_upgrade_time", owner_id=user_id).pack()
        )])
    elif batch_timer: 
        if now >= batch_timer:
            reward = brew_stats.get('reward', 0)
            total = reward * farm.get('brewery_batch_size', 0)
            kb.append([InlineKeyboardButton(text=f"🏆 Забрать +{total} 🍺", callback_data=BreweryCallback(action="collect", owner_id=user_id).pack())])
        else:
            kb.append([InlineKeyboardButton(
                text="🏭 Пивоварня · варится",
                callback_data=BreweryCallback(action="brew_menu", owner_id=user_id).pack()
            )])
    else:
        kb.append([InlineKeyboardButton(text="🏭 Пивоварня", callback_data=BreweryCallback(action="brew_menu", owner_id=user_id).pack())])

    # Остальные кнопки 
    kb_buttons = [
        InlineKeyboardButton(text="📋 Заказы", callback_data=FarmCallback(action="orders_menu", owner_id=user_id).pack()),
        
        InlineKeyboardButton(text="📦 Склад",     callback_data=FarmCallback(action="inventory", owner_id=user_id).pack()),
        InlineKeyboardButton(text="⭐ Улучшения", callback_data=FarmCallback(action="upgrades",  owner_id=user_id).pack()),
        InlineKeyboardButton(text="🏪 Магазин",   callback_data=FarmCallback(action="shop",      owner_id=user_id).pack()),
        InlineKeyboardButton(text="❓ Как играть?", callback_data=FarmCallback(action="show_help", owner_id=user_id).pack())
    ]
    kb += rows(kb_buttons, per_row=2)
    if show_main_menu:
        kb.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data=FarmCallback(action="main_menu", owner_id=user_id).pack())])

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
    
    raw = await db.get_user_plots(user_id)
    active = {}
    for plot_num, crop_id, ready_str in raw:
        if isinstance(ready_str, str):
            active[plot_num] = (crop_id, datetime.fromisoformat(ready_str))

    empty_plots_count = max_plots - len(active)
    plot_status_lines = []
    if empty_plots_count <= 0:
        for i in range(1, max_plots + 1):
            if i not in active:
                continue

            seed_id, ready = active[i]
            product_id = SEED_TO_PRODUCT_ID.get(seed_id, '??')
            crop_name = safe_name(CROP_SHORT, product_id, "??")
            if now >= ready:
                plot_status_lines.append(f"Грядка {i}: {crop_name} — <b>готово</b>")
            else:
                left = format_time_delta(ready - now)
                plot_status_lines.append(f"Грядка {i}: {crop_name} — <b>{left}</b>")

    if empty_plots_count > 0:
        field_note = "Выбери свободную грядку, чтобы посадить семена."
    else:
        field_note = "Свободных грядок нет.\n\n" + "\n".join(plot_status_lines)

    text = (
        f"🌾 <b>Поле</b> · ур. <b>{lvl}</b>\n\n"
        f"Грядок: <b>{stats.get('plots', '??')}</b>\n"
        f"Шанс x2: <b>{stats.get('chance_x2', '??')}%</b>\n"
        f"Рост: 🌾 <b>{g_time}м</b> / 🌱 <b>{h_time}м</b>\n\n"
        f"{DIVIDER}\n"
        f"{field_note}"
    )

    per_row = 2 if max_plots <= 4 else 3
    plot_btns = []
    for i in range(1, max_plots + 1):
        if i in active:
            seed_id, ready = active[i]

            product_id = SEED_TO_PRODUCT_ID.get(seed_id, '??')
            crop_name = safe_name(CROP_SHORT, product_id, "??")

            if now >= ready:
                txt = f"✅ {crop_name} · собрать"
                cb  = PlotCallback(action="harvest", owner_id=user_id, plot_num=i).pack()
                plot_btns.append(InlineKeyboardButton(text=txt, callback_data=cb))
            else:
                continue

        else:
            txt = f"🟦 Грядка {i}"
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
        text, keyboard = await get_farm_dashboard(
            user_id,
            message.from_user.full_name,
            db,
            show_main_menu=message.chat.type == "private",
        )
        await answer_to_trigger(message, text, reply_markup=keyboard)
    except Exception as e:
        logging.error(f"Critical error in cmd_farm: {e}", exc_info=True)
        await answer_to_trigger(message, "⛔ Ошибка при загрузке Фермы!")

@farm_router.message(GroupTextAlias(*FARM_ALIASES))
async def alias_farm(message: Message, bot: Bot, db: Database):
    await cmd_farm(message, bot, db)


@farm_router.callback_query(FarmCallback.filter(F.action == "main_dashboard"))
async def cq_farm_main_dashboard(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    try:
        text, keyboard = await get_farm_dashboard(
            callback.from_user.id,
            callback.from_user.full_name,
            db,
            show_main_menu=callback.message.chat.type == "private",
        )
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        logging.error(f"Dash error: {e}")
    await callback.answer()


@farm_router.callback_query(FarmCallback.filter(F.action == "main_menu"))
async def cq_farm_main_menu(callback: CallbackQuery, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data.owner_id): return
    if callback.message.chat.type != "private":
        await callback.answer("Главное меню открывается в личке с ботом.", show_alert=True)
        return

    text = get_private_start_text(callback.from_user.full_name, False)
    keyboard = get_main_menu_keyboard(callback.from_user.id)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')
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
            f"📦 <b>Склад</b>\n\n"
            f"Сырье для варки и семена для поля.\n\n"
            f"{DIVIDER}\n"
            f"<b>Урожай</b>\n"
            f"🌾 Зерно: <b>{inv['зерно']}</b>\n"
            f"🌱 Хмель: <b>{inv['хмель']}</b>\n\n"
            f"<b>Семена</b>\n"
            f"🌾 Зерно: <b>{inv['семя_зерна']}</b>\n"
            f"🌱 Хмель: <b>{inv['семя_хмеля']}</b>"
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
            "Заказы обновляются раз в 24 часа и подбираются под дневной запас магазина.\n\n"
            f"{DIVIDER}\n"
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
    
    text = (
        f"🌱 <b>Посадка</b> · грядка <b>{callback_data.plot_num}</b>\n\n"
        f"{DIVIDER}\n"
        f"Семена на складе:\n"
        f"🌾 Зерно: <b>{inv['семя_зерна']}</b>\n"
        f"🌱 Хмель: <b>{inv['семя_хмеля']}</b>"
    )
    btns = []
    if inv['семя_зерна'] > 0:
        btns.append(InlineKeyboardButton(text="Посадить 🌾 Зерно", callback_data=PlotCallback(action="plant_do", owner_id=user_id, plot_num=callback_data.plot_num, crop_id="g").pack()))
    if inv['семя_хмеля'] > 0:
        btns.append(InlineKeyboardButton(text="Посадить 🌱 Хмель", callback_data=PlotCallback(action="plant_do", owner_id=user_id, plot_num=callback_data.plot_num, crop_id="h").pack()))
    
    rows_kb = rows(btns, 1)
    if not btns:
        text += "\n\n<i>Семян нет. Загляни в магазин.</i>"
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
        await db.add_harvest_stat(callback.from_user.id, prod, 1)
        await callback.answer(f"Собрано: 1 {FARM_ITEM_NAMES[prod]}")
        await cq_farm_view_plots(callback, FarmCallback(action="view_plots", owner_id=callback.from_user.id), db)
    else:
        await callback.answer("Ошибка сбора", show_alert=True)

@farm_router.callback_query(PlotCallback.filter(F.action == "show_time"))
async def cq_plot_time(callback: CallbackQuery, callback_data: PlotCallback):
    if not await check_owner(callback, callback_data.owner_id): return
    await callback.answer("Еще растет...", show_alert=True)

# --- ПИВОВАРНЯ ---
@farm_router.callback_query(BreweryCallback.filter(F.action == "brew_menu"))
async def cq_brewery_menu(callback: CallbackQuery, callback_data: BreweryCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    uid = callback.from_user.id
    farm = await db.get_user_farm_data(uid)
    inv = await db.get_user_inventory(uid)
    stats = get_level_data(farm.get('brewery_level', 1), BREWERY_UPGRADES)
    batch_timer = farm.get('brewery_batch_timer_end')
    now = datetime.now()

    btns = []
    if batch_timer:
        batch_size = farm.get('brewery_batch_size', 0)
        reward = stats.get('reward', 0)
        total_reward = reward * batch_size

        if now >= batch_timer:
            status_text = (
                "Партия готова.\n"
                f"Готово: 🍺 Пиво <b>x{batch_size}</b>\n"
                f"Награда: <b>+{total_reward}</b> 🍺"
            )
            btns.append(
                InlineKeyboardButton(
                    text=f"🏆 Забрать +{total_reward} 🍺",
                    callback_data=BreweryCallback(action="collect", owner_id=uid).pack()
                )
            )
        else:
            left = format_time_delta(batch_timer - now)
            status_text = (
                "Партия сейчас варится.\n"
                f"Варится: 🍺 Пиво <b>x{batch_size}</b>\n"
                f"Осталось: <b>{left}</b>"
            )

        text = (
            "🏭 <b>Пивоварня</b>\n\n"
            f"{status_text}\n\n"
            f"{DIVIDER}\n"
            "<i>Когда варка закончится, здесь появится кнопка сбора.</i>"
        )

        kb = rows(btns, 1)
        kb.append(back_btn_to_farm(uid))
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        await callback.answer()
        return

    missing_grain = max(0, BREWERY_RECIPE['зерно'] - inv['зерно'])
    missing_hops = max(0, BREWERY_RECIPE['хмель'] - inv['хмель'])
    text = (
        "🏭 <b>Пивоварня</b>\n\n"
        "Рецепт на 1 варку:\n"
        f"🌾 Зерно: <b>{BREWERY_RECIPE['зерно']}</b>\n"
        f"🌱 Хмель: <b>{BREWERY_RECIPE['хмель']}</b>\n\n"
        f"{DIVIDER}\n"
        "На складе:\n"
        f"🌾 Зерно: <b>{inv['зерно']}</b>\n"
        f"🌱 Хмель: <b>{inv['хмель']}</b>"
    )
    if missing_grain or missing_hops:
        missing_parts = []
        if missing_grain:
            missing_parts.append(f"🌾 {missing_grain}")
        if missing_hops:
            missing_parts.append(f"🌱 {missing_hops}")
        text += f"\n\n<i>Не хватает: {' / '.join(missing_parts)}</i>"
    
    can_brew = inv['зерно'] >= BREWERY_RECIPE['зерно'] and inv['хмель'] >= BREWERY_RECIPE['хмель']
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
    if not await check_owner(callback, callback_data.owner_id): return
    farm = await db.get_user_farm_data(callback_data.owner_id)
    if farm.get('brewery_batch_timer_end'):
         left = format_time_delta(farm['brewery_batch_timer_end'] - datetime.now())
         await callback.answer(f"⏳ Варится... {left}", show_alert=True)
    else:
         await callback.answer("Не варится.")

@farm_router.callback_query(FarmCallback.filter(F.action == "show_upgrade_time"))
async def cq_show_upgrade_time(callback: CallbackQuery, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data.owner_id): return
    await callback.answer("⏳ Идет стройка...", show_alert=True)


# --- УЛУЧШЕНИЯ ---
@farm_router.callback_query(FarmCallback.filter(F.action == "upgrades"))
async def cq_farm_upgrades(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    user_id = callback.from_user.id
    balance = await db.get_user_beer_rating(user_id)
    farm = await db.get_user_farm_data(user_id)
    active_plots = await db.get_user_plots(user_id)
    field_is_free = len(active_plots) == 0
    brewery_is_free = not farm.get('brewery_batch_timer_end')
    
    text = (
        f"⭐ <b>Улучшения</b>\n\n"
        f"Баланс: <b>{balance}</b> 🍺\n\n"
        f"{DIVIDER}\n"
    )
    buttons = []

    # Поле
    f_lvl = farm.get('field_level', 1)
    f_current = get_level_data(f_lvl, FIELD_UPGRADES)
    text += f"🌾 <b>Поле</b> · ур. <b>{f_lvl}</b>\n"
    text += (
        "<b>Сейчас:</b>\n"
        f"• Грядки: <b>{f_current.get('plots', '??')}</b>\n"
        f"• Шанс x2: <b>{f_current.get('chance_x2', '??')}%</b>\n"
        f"• Рост: 🌾 <b>{f_current.get('grow_time_min', {}).get('зерно', '??')}м</b> / "
        f"🌱 <b>{f_current.get('grow_time_min', {}).get('хмель', '??')}м</b>\n"
    )
    if farm.get('field_upgrade_timer_end'):
        left = format_time_delta(farm['field_upgrade_timer_end'] - datetime.now())
        text += f"<i>Улучшается: {left}</i>\n"
    elif f_current.get('max_level'):
        text += "<b>Максимальный уровень.</b>\n"
    else:
        f_next = get_level_data(f_lvl + 1, FIELD_UPGRADES)
        cost = f_next['cost']
        text += (
            f"<b>После улучшения · ур. {f_lvl + 1}:</b>\n"
            f"• Грядки: <b>{f_next.get('plots', '??')}</b>\n"
            f"• Шанс x2: <b>{f_next.get('chance_x2', '??')}%</b>\n"
            f"• Рост: 🌾 <b>{f_next.get('grow_time_min', {}).get('зерно', '??')}м</b> / "
            f"🌱 <b>{f_next.get('grow_time_min', {}).get('хмель', '??')}м</b>\n"
            f"<b>Стоимость:</b> {cost} 🍺 · <b>Время:</b> {f_next['time_h']} ч\n"
        )
        if not field_is_free:
            text += "<i>Перед улучшением поле должно быть свободным.</i>\n"
        if balance >= cost and field_is_free:
            buttons.append([InlineKeyboardButton(text="⬆️ Улучшить поле", callback_data=UpgradeCallback(action="buy_field", owner_id=user_id).pack())])
    
    text += "\n" # Разделитель
    
    # Пивоварня
    b_lvl = farm.get('brewery_level', 1)
    b_current = get_level_data(b_lvl, BREWERY_UPGRADES)
    text += f"🏭 <b>Пивоварня</b> · ур. <b>{b_lvl}</b>\n"
    text += (
        "<b>Сейчас:</b>\n"
        f"• Награда: <b>+{b_current.get('reward', '??')}</b> 🍺\n"
        f"• Варка: <b>{b_current.get('brew_time_min', '??')}м</b>\n"
    )
    if farm.get('brewery_upgrade_timer_end'):
        left = format_time_delta(farm['brewery_upgrade_timer_end'] - datetime.now())
        text += f"<i>Улучшается: {left}</i>\n"
    elif b_current.get('max_level'):
        text += "<b>Максимальный уровень.</b>\n"
    else:
        b_next = get_level_data(b_lvl + 1, BREWERY_UPGRADES)
        cost = b_next['cost']
        text += (
            f"<b>После улучшения · ур. {b_lvl + 1}:</b>\n"
            f"• Награда: <b>+{b_next.get('reward', '??')}</b> 🍺\n"
            f"• Варка: <b>{b_next.get('brew_time_min', '??')}м</b>\n"
            f"<b>Стоимость:</b> {cost} 🍺 · <b>Время:</b> {b_next['time_h']} ч\n"
        )
        if not brewery_is_free:
            text += "<i>Перед улучшением пивоварня должна быть свободной.</i>\n"
        if balance >= cost and brewery_is_free:
            buttons.append([InlineKeyboardButton(text="⬆️ Улучшить пивоварню", callback_data=UpgradeCallback(action="buy_brewery", owner_id=user_id).pack())])

    buttons.append(back_btn_to_farm(user_id))
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@farm_router.callback_query(UpgradeCallback.filter(F.action.in_({"buy_field", "buy_brewery"})))
async def cq_upgrade_confirm(callback: CallbackQuery, callback_data: UpgradeCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id): return
    user_id = callback.from_user.id
    b_type = "field" if callback_data.action == "buy_field" else "brewery"
    farm = await db.get_user_farm_data(user_id)
    now = datetime.now()

    if b_type == "field":
        if farm.get('field_upgrade_timer_end') and now < farm['field_upgrade_timer_end']:
            return await callback.answer("⏳ Поле уже улучшается.", show_alert=True)
        if await db.get_user_plots(user_id):
            return await callback.answer("🌾 Сначала освободи поле: собери урожай или дождись роста.", show_alert=True)
    else:
        if farm.get('brewery_upgrade_timer_end') and now < farm['brewery_upgrade_timer_end']:
            return await callback.answer("⏳ Пивоварня уже улучшается.", show_alert=True)
        if farm.get('brewery_batch_timer_end'):
            return await callback.answer("🏭 Сначала освободи пивоварню: дождись варки и забери партию.", show_alert=True)

    lvl = farm.get(f'{b_type}_level', 1)
    current = get_level_data(lvl, FIELD_UPGRADES if b_type == 'field' else BREWERY_UPGRADES)
    if current.get('max_level'):
        return await callback.answer("⭐ Уже максимальный уровень.", show_alert=True)

    stats = get_level_data(lvl + 1, FIELD_UPGRADES if b_type == 'field' else BREWERY_UPGRADES)
    balance = await db.get_user_beer_rating(user_id)
    if balance < stats['cost']:
        return await callback.answer(f"⛔ Нужно {stats['cost']} 🍺.", show_alert=True)

    await db.start_upgrade(user_id, b_type, now + timedelta(hours=stats['time_h']), stats['cost'])
    await callback.answer("Стройка началась!")
    await cq_farm_main_dashboard(callback, FarmCallback(action="main_dashboard", owner_id=user_id), db)

@farm_router.callback_query(FarmCallback.filter(F.action == "show_help"))
async def cq_farm_help(callback: CallbackQuery, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data.owner_id): return
    text = get_farm_help_text()
    kb = [back_btn_to_farm(callback.from_user.id)]
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

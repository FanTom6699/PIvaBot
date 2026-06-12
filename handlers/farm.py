import logging
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import Database
from utils import answer_to_trigger, format_time_delta, mention_user
from .common import (
    check_user_registered,
    format_xp_progress,
    get_main_menu_keyboard,
    get_private_start_text,
    get_xp_level,
)
from .farm_config import (
    BARN_CAPACITY,
    BARN_ITEMS,
    CHICKEN_COUNT,
    CROP_CODE_TO_ID,
    CROP_SHORT,
    EGG_ID,
    EGG_PRODUCTION_MINUTES,
    EGG_XP_PER_ITEM,
    FARM_ITEM_NAMES,
    FARM_ORDER_POOL,
    ORDER_COOLDOWN_MINUTES,
    SILO_CAPACITY,
    SILO_ITEMS,
    START_FIELD_COUNT,
    WHEAT_GROW_MINUTES,
    WHEAT_HARVEST_AMOUNT,
    WHEAT_ID,
    WHEAT_PLANT_COST,
    WHEAT_XP_PER_ITEM,
)
from .text_aliases import FARM_ALIASES, GroupTextAlias

farm_router = Router()
DIVIDER = "<code>--- --- ---</code>"
PLOTS_PER_PAGE = 25


class FarmCallback(CallbackData, prefix="farm"):
    action: str
    owner_id: int


class FarmPageCallback(CallbackData, prefix="fpage"):
    action: str
    owner_id: int
    page: int = 0


class PlotCallback(CallbackData, prefix="plot"):
    action: str
    owner_id: int
    plot_num: int
    crop_id: Optional[str] = None


class OrderCallback(CallbackData, prefix="order"):
    action: str
    owner_id: int
    order_id: str


def rows(buttons: list[InlineKeyboardButton], per_row: int) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def back_btn_to_farm(user_id: int) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="⬅️ Назад", callback_data=FarmCallback(action="main_dashboard", owner_id=user_id).pack())]


def back_btn_to_fields(user_id: int) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="⬅️ Назад", callback_data=FarmCallback(action="view_plots", owner_id=user_id).pack())]


def storage_used(inventory: dict, items: list[tuple[str, str]]) -> int:
    return sum(max(0, int(inventory.get(item_id, 0))) for item_id, _ in items)


def get_active_plot_map(active_plots: list) -> dict[int, tuple[str, datetime]]:
    active = {}
    for plot_num, crop_id, ready_str in active_plots:
        if plot_num > START_FIELD_COUNT:
            continue
        try:
            ready_dt = datetime.fromisoformat(ready_str) if isinstance(ready_str, str) else ready_str
        except (TypeError, ValueError):
            continue
        if ready_dt:
            active[plot_num] = (crop_id, ready_dt)
    return active


def get_plot_counts(active_plots: list, now: datetime) -> dict[str, int]:
    active = get_active_plot_map(active_plots)
    ready = sum(1 for _, ready in active.values() if now >= ready)
    growing = sum(1 for _, ready in active.values() if now < ready)
    free = max(0, START_FIELD_COUNT - ready - growing)
    return {"total": START_FIELD_COUNT, "free": free, "growing": growing, "ready": ready}


def item_lines(items: dict[str, int], inventory: dict) -> list[str]:
    return [
        f"{FARM_ITEM_NAMES.get(item_id, item_id)}: <b>{amount}</b>"
        for item_id, amount in items.items()
    ]


def order_items_text(order: dict, inventory: dict) -> str:
    lines = []
    for item_id, needed in order["items"].items():
        have = inventory.get(item_id, 0)
        lines.append(f"• {FARM_ITEM_NAMES.get(item_id, item_id)}: <b>{min(have, needed)}/{needed}</b>")
    return "\n".join(lines)


def can_complete_order(order: dict, inventory: dict) -> bool:
    return all(inventory.get(item_id, 0) >= amount for item_id, amount in order["items"].items())


def format_level_alert(old_xp: int, new_xp: int) -> str:
    old_level, _ = get_xp_level(old_xp)
    new_level, title = get_xp_level(new_xp)
    if new_level <= old_level:
        return ""
    return f"\nНовый уровень: {new_level} — {title}"


async def add_xp_and_get_alert(db: Database, user_id: int, amount: int, source: str) -> tuple[int, str]:
    result = await db.add_xp(user_id, amount, source=source)
    return result["new_xp"], format_level_alert(result["old_xp"], result["new_xp"])


async def check_owner(callback: CallbackQuery, owner_id: int) -> bool:
    if callback.from_user.id != owner_id:
        await callback.answer("⛔ Это не твоя ферма.", show_alert=True)
        return False
    return True


async def edit_farm_message(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup):
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


async def get_farm_dashboard(user_id: int, user_name: str, db: Database, show_main_menu: bool = True) -> tuple[str, InlineKeyboardMarkup]:
    inventory = await db.get_user_inventory(user_id)
    active_plots = await db.get_user_plots(user_id)
    now = datetime.now()
    counts = get_plot_counts(active_plots, now)

    xp = await db.get_user_xp(user_id)
    level, title = get_xp_level(xp)
    silo_used = storage_used(inventory, SILO_ITEMS)
    barn_used = storage_used(inventory, BARN_ITEMS)

    text = (
        "🌾 <b>Ферма</b>\n\n"
        f"<b>{mention_user(user_id, user_name)}</b>\n"
        f"Уровень: <b>{level}</b> — <b>{title}</b>\n"
        f"XP: <b>{format_xp_progress(level, xp)}</b> ⭐\n\n"
        f"{DIVIDER}\n"
        f"Поля: <b>{counts['total']}</b>\n"
        f"Свободно: <b>{counts['free']}</b>\n"
        f"Растёт: <b>{counts['growing']}</b>\n"
        f"Готово: <b>{counts['ready']}</b>\n\n"
        f"🌾 Силос: <b>{silo_used} / {SILO_CAPACITY}</b>\n"
        f"📦 Амбар: <b>{barn_used} / {BARN_CAPACITY}</b>"
    )

    keyboard_rows = [
        [
            InlineKeyboardButton(text="🌱 Поля", callback_data=FarmCallback(action="view_plots", owner_id=user_id).pack()),
            InlineKeyboardButton(text="🐔 Животные", callback_data=FarmCallback(action="animals", owner_id=user_id).pack()),
        ],
        [
            InlineKeyboardButton(text="🏭 Производство", callback_data=FarmCallback(action="production", owner_id=user_id).pack()),
            InlineKeyboardButton(text="📦 Амбар", callback_data=FarmCallback(action="barn", owner_id=user_id).pack()),
        ],
        [
            InlineKeyboardButton(text="🌾 Силос", callback_data=FarmCallback(action="silo", owner_id=user_id).pack()),
            InlineKeyboardButton(text="🚚 Заказы", callback_data=FarmCallback(action="orders_menu", owner_id=user_id).pack()),
        ],
    ]
    if show_main_menu:
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=FarmCallback(action="main_menu", owner_id=user_id).pack())])

    return text, InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


async def get_plots_dashboard(user_id: int, db: Database) -> tuple[str, InlineKeyboardMarkup]:
    inventory = await db.get_user_inventory(user_id)
    active = get_active_plot_map(await db.get_user_plots(user_id))
    now = datetime.now()
    counts = get_plot_counts(await db.get_user_plots(user_id), now)

    text = (
        "🌱 <b>Поля</b>\n\n"
        f"{DIVIDER}\n"
        f"Всего грядок: <b>{counts['total']}</b>\n"
        f"Свободные грядки: <b>{counts['free']}</b>\n"
        f"Растущие культуры: <b>{counts['growing']}</b>\n"
        f"Готовые культуры: <b>{counts['ready']}</b>\n\n"
        f"Посадка: <b>{WHEAT_PLANT_COST}</b> 🌾 пшеница\n"
        f"Рост: <b>{WHEAT_GROW_MINUTES} мин.</b>\n"
        f"Сбор: <b>+{WHEAT_HARVEST_AMOUNT}</b> 🌾 пшеницы и <b>+{WHEAT_HARVEST_AMOUNT * WHEAT_XP_PER_ITEM}</b> XP\n"
        f"В силосе: <b>{inventory.get(WHEAT_ID, 0)}</b> 🌾"
    )

    buttons = []
    if counts["free"] > 0:
        buttons.append([InlineKeyboardButton(text="🌱 Засадить все свободные поля", callback_data=FarmCallback(action="plant_all", owner_id=user_id).pack())])
    if counts["ready"] > 0:
        buttons.append([InlineKeyboardButton(text="✅ Собрать всё готовое", callback_data=FarmCallback(action="harvest_ready", owner_id=user_id).pack())])

    for plot_num in range(1, START_FIELD_COUNT + 1):
        plot = active.get(plot_num)
        if not plot:
            buttons.append([InlineKeyboardButton(
                text=f"🌱 Поле {plot_num} · посадить",
                callback_data=PlotCallback(action="plant_do", owner_id=user_id, plot_num=plot_num, crop_id="w").pack(),
            )])
            continue

        crop_id, ready_at = plot
        crop_name = CROP_SHORT.get(crop_id, CROP_SHORT[WHEAT_ID])
        if now >= ready_at:
            buttons.append([InlineKeyboardButton(
                text=f"✅ Поле {plot_num} · собрать",
                callback_data=PlotCallback(action="harvest", owner_id=user_id, plot_num=plot_num).pack(),
            )])
        else:
            left = format_time_delta(ready_at - now)
            buttons.append([InlineKeyboardButton(text=f"⏳ Поле {plot_num} · {crop_name} · {left}", callback_data=PlotCallback(action="show_time", owner_id=user_id, plot_num=plot_num).pack())])

    buttons.append([InlineKeyboardButton(text="📋 Список грядок", callback_data=FarmPageCallback(action="plot_list", owner_id=user_id, page=0).pack())])
    buttons.append(back_btn_to_farm(user_id))
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


async def get_plot_list_page(user_id: int, db: Database, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    active = get_active_plot_map(await db.get_user_plots(user_id))
    now = datetime.now()
    page = max(0, page)
    total_pages = max(1, (START_FIELD_COUNT + PLOTS_PER_PAGE - 1) // PLOTS_PER_PAGE)
    page = min(page, total_pages - 1)
    start_plot = page * PLOTS_PER_PAGE + 1
    end_plot = min(START_FIELD_COUNT, start_plot + PLOTS_PER_PAGE - 1)

    text = (
        "📋 <b>Список грядок</b>\n\n"
        f"Экран: <b>{page + 1}/{total_pages}</b>\n"
        f"Грядки: <b>{start_plot}-{end_plot}</b> из <b>{START_FIELD_COUNT}</b>\n\n"
        f"{DIVIDER}\n"
    )

    buttons = []
    for plot_num in range(start_plot, end_plot + 1):
        plot = active.get(plot_num)
        if not plot:
            text += f"Поле {plot_num}: <b>свободно</b>\n"
            buttons.append([InlineKeyboardButton(
                text=f"🌱 Поле {plot_num} · посадить",
                callback_data=PlotCallback(action="plant_do", owner_id=user_id, plot_num=plot_num, crop_id="w").pack(),
            )])
            continue

        crop_id, ready_at = plot
        crop_name = CROP_SHORT.get(crop_id, CROP_SHORT[WHEAT_ID])
        if now >= ready_at:
            text += f"Поле {plot_num}: {crop_name} — <b>готово</b>\n"
            buttons.append([InlineKeyboardButton(
                text=f"✅ Поле {plot_num} · собрать",
                callback_data=PlotCallback(action="harvest", owner_id=user_id, plot_num=plot_num).pack(),
            )])
        else:
            text += f"Поле {plot_num}: {crop_name} — <b>{format_time_delta(ready_at - now)}</b>\n"

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=FarmPageCallback(action="plot_list", owner_id=user_id, page=page - 1).pack()))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=FarmPageCallback(action="plot_list", owner_id=user_id, page=page + 1).pack()))
    if nav:
        buttons.append(nav)

    buttons.append(back_btn_to_fields(user_id))
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


async def get_animals_menu(user_id: int, db: Database) -> tuple[str, InlineKeyboardMarkup]:
    farm = await db.get_user_farm_data(user_id)
    chicken_count = farm.get("chicken_count") or CHICKEN_COUNT
    timer_end = farm.get("chicken_timer_end")
    now = datetime.now()
    buttons = []

    if not timer_end:
        timer_end = now + timedelta(minutes=EGG_PRODUCTION_MINUTES)
        await db.set_chicken_timer(user_id, timer_end)

    if now >= timer_end:
        status = f"Готово к сбору: <b>{chicken_count}</b> 🥚"
        buttons.append([InlineKeyboardButton(text=f"🥚 Собрать яйца x{chicken_count}", callback_data=FarmCallback(action="collect_eggs", owner_id=user_id).pack())])
    else:
        status = f"До яиц: <b>{format_time_delta(timer_end - now)}</b>"

    text = (
        "🐔 <b>Животные</b>\n\n"
        f"{DIVIDER}\n"
        f"Курятник: <b>есть</b>\n"
        f"Куры: <b>{chicken_count}</b>\n"
        f"{status}\n\n"
        f"Каждая курица даёт <b>1</b> 🥚 за <b>{EGG_PRODUCTION_MINUTES} мин.</b>\n"
        f"Сбор яйца: <b>+{EGG_XP_PER_ITEM}</b> XP"
    )
    buttons.append(back_btn_to_farm(user_id))
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


async def get_barn_menu(user_id: int, db: Database) -> tuple[str, InlineKeyboardMarkup]:
    inventory = await db.get_user_inventory(user_id)
    used = storage_used(inventory, BARN_ITEMS)
    text = (
        f"📦 <b>Амбар: {used} / {BARN_CAPACITY}</b>\n\n"
        + "\n".join(f"{label}: <b>{inventory.get(item_id, 0)}</b>" for item_id, label in BARN_ITEMS)
        + "\n\n<i>Амбар хранит продукты и ресурсы.</i>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬆️ Улучшить амбар", callback_data=FarmCallback(action="storage_upgrade_info", owner_id=user_id).pack())],
        back_btn_to_farm(user_id),
    ])
    return text, keyboard


async def get_silo_menu(user_id: int, db: Database) -> tuple[str, InlineKeyboardMarkup]:
    inventory = await db.get_user_inventory(user_id)
    used = storage_used(inventory, SILO_ITEMS)
    text = (
        f"🌾 <b>Силос: {used} / {SILO_CAPACITY}</b>\n\n"
        + "\n".join(f"{label}: <b>{inventory.get(item_id, 0)}</b>" for item_id, label in SILO_ITEMS)
        + "\n\n<i>Силос хранит культуры с полей.</i>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬆️ Улучшить силос", callback_data=FarmCallback(action="storage_upgrade_info", owner_id=user_id).pack())],
        back_btn_to_farm(user_id),
    ])
    return text, keyboard


def get_production_menu(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "🏭 <b>Производство</b>\n\n"
        "Скоро здесь появятся здания для переработки ресурсов.\n\n"
        f"{DIVIDER}\n"
        "Пока стартовый цикл фермы работает через поля, курятник и заказы."
    )
    return text, InlineKeyboardMarkup(inline_keyboard=[back_btn_to_farm(user_id)])


async def get_orders_menu(user_id: int, db: Database) -> tuple[str, InlineKeyboardMarkup]:
    order_id, next_order_time = await db.get_current_order(user_id)
    inventory = await db.get_user_inventory(user_id)

    if next_order_time:
        text = (
            "🚚 <b>Доска заказов</b>\n\n"
            "Новый заказ ещё готовится.\n\n"
            f"{DIVIDER}\n"
            f"До нового заказа: <b>{format_time_delta(next_order_time - datetime.now())}</b>"
        )
        return text, InlineKeyboardMarkup(inline_keyboard=[back_btn_to_farm(user_id)])

    order = FARM_ORDER_POOL.get(order_id)
    if not order:
        text = "🚚 <b>Доска заказов</b>\n\nЗаказ не найден. Открой доску ещё раз."
        return text, InlineKeyboardMarkup(inline_keyboard=[back_btn_to_farm(user_id)])

    status = "🟢 Можно выполнить" if can_complete_order(order, inventory) else "🔴 Не хватает ресурсов"
    text = (
        "🚚 <b>Доска заказов</b>\n\n"
        "На доске висит один заказ. После выполнения новый появится через 30 минут.\n\n"
        f"{DIVIDER}\n"
        f"<b>{order['title']}</b>\n"
        f"{status}\n\n"
        "<b>Нужно:</b>\n"
        f"{order_items_text(order, inventory)}\n\n"
        f"<b>Награда:</b> +{order['reward_amount']} 🍺 и +{order['reward_xp']} XP"
    )

    buttons = []
    if can_complete_order(order, inventory):
        buttons.append([InlineKeyboardButton(
            text=f"✅ Выполнить заказ · +{order['reward_amount']} 🍺",
            callback_data=OrderCallback(action="complete", owner_id=user_id, order_id=order_id).pack(),
        )])
    buttons.append(back_btn_to_farm(user_id))
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


async def harvest_plot(user_id: int, plot_num: int, db: Database) -> tuple[bool, str]:
    active = get_active_plot_map(await db.get_user_plots(user_id))
    plot = active.get(plot_num)
    if not plot:
        return False, "Это поле пустое."

    _, ready_at = plot
    if datetime.now() < ready_at:
        return False, "Пшеница ещё растёт."

    inventory = await db.get_user_inventory(user_id)
    if storage_used(inventory, SILO_ITEMS) + WHEAT_HARVEST_AMOUNT > SILO_CAPACITY:
        return False, "В силосе нет места для урожая."

    crop_id = await db.harvest_plot(user_id, plot_num)
    if not crop_id:
        return False, "Не получилось собрать поле."

    await db.modify_inventory(user_id, WHEAT_ID, WHEAT_HARVEST_AMOUNT)
    await db.add_harvest_stat(user_id, "зерно", WHEAT_HARVEST_AMOUNT)
    xp_amount = WHEAT_HARVEST_AMOUNT * WHEAT_XP_PER_ITEM
    _, level_alert = await add_xp_and_get_alert(db, user_id, xp_amount, "wheat_harvest")
    return True, f"Собрано: +{WHEAT_HARVEST_AMOUNT} 🌾 пшеницы\n+{xp_amount} XP{level_alert}"


@farm_router.message(Command("farm"))
async def cmd_farm(message: Message, bot: Bot, db: Database):
    user_id = message.from_user.id
    if not await check_user_registered(message, bot, db):
        return
    try:
        text, keyboard = await get_farm_dashboard(
            user_id,
            message.from_user.full_name,
            db,
            show_main_menu=message.chat.type == "private",
        )
        await answer_to_trigger(message, text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Critical error in cmd_farm: {e}", exc_info=True)
        await answer_to_trigger(message, "⛔ Ошибка при загрузке фермы.")


@farm_router.message(GroupTextAlias(*FARM_ALIASES))
async def alias_farm(message: Message, bot: Bot, db: Database):
    await cmd_farm(message, bot, db)


@farm_router.callback_query(FarmCallback.filter(F.action == "main_dashboard"))
async def cq_farm_main_dashboard(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id):
        return
    text, keyboard = await get_farm_dashboard(
        callback.from_user.id,
        callback.from_user.full_name,
        db,
        show_main_menu=callback.message.chat.type == "private",
    )
    await edit_farm_message(callback, text, keyboard)
    await callback.answer()


@farm_router.callback_query(FarmCallback.filter(F.action == "main_menu"))
async def cq_farm_main_menu(callback: CallbackQuery, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data.owner_id):
        return
    if callback.message.chat.type != "private":
        await callback.answer("Главное меню открывается в личке с ботом.", show_alert=True)
        return
    text = get_private_start_text(callback.from_user.full_name, False)
    keyboard = get_main_menu_keyboard(callback.from_user.id)
    await edit_farm_message(callback, text, keyboard)
    await callback.answer()


@farm_router.callback_query(FarmCallback.filter(F.action == "view_plots"))
async def cq_farm_view_plots(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id):
        return
    text, keyboard = await get_plots_dashboard(callback.from_user.id, db)
    await edit_farm_message(callback, text, keyboard)
    await callback.answer()


@farm_router.callback_query(FarmPageCallback.filter(F.action == "plot_list"))
async def cq_farm_plot_list(callback: CallbackQuery, callback_data: FarmPageCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id):
        return
    text, keyboard = await get_plot_list_page(callback.from_user.id, db, callback_data.page)
    await edit_farm_message(callback, text, keyboard)
    await callback.answer()


@farm_router.callback_query(FarmCallback.filter(F.action == "plant_all"))
async def cq_farm_plant_all(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id):
        return
    user_id = callback.from_user.id
    active = get_active_plot_map(await db.get_user_plots(user_id))
    free_plots = [plot_num for plot_num in range(1, START_FIELD_COUNT + 1) if plot_num not in active]
    if not free_plots:
        await callback.answer("Свободных полей нет.", show_alert=True)
        return

    inventory = await db.get_user_inventory(user_id)
    required = len(free_plots) * WHEAT_PLANT_COST
    if inventory.get(WHEAT_ID, 0) < required:
        await callback.answer(f"Нужно {required} 🌾 пшеницы. Сейчас: {inventory.get(WHEAT_ID, 0)}.", show_alert=True)
        return

    planted = 0
    for plot_num in free_plots:
        if not await db.modify_inventory(user_id, WHEAT_ID, -WHEAT_PLANT_COST):
            break
        ready_at = datetime.now() + timedelta(minutes=WHEAT_GROW_MINUTES)
        if await db.plant_crop(user_id, plot_num, WHEAT_ID, ready_at):
            planted += 1
        else:
            await db.modify_inventory(user_id, WHEAT_ID, WHEAT_PLANT_COST)

    await callback.answer(f"Засажено полей: {planted}.")
    await cq_farm_view_plots(callback, FarmCallback(action="view_plots", owner_id=user_id), db)


@farm_router.callback_query(FarmCallback.filter(F.action == "harvest_ready"))
async def cq_farm_harvest_ready(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id):
        return
    user_id = callback.from_user.id
    active = get_active_plot_map(await db.get_user_plots(user_id))
    now = datetime.now()
    ready_plots = [plot_num for plot_num, (_, ready_at) in active.items() if now >= ready_at]
    if not ready_plots:
        await callback.answer("Готового урожая пока нет.", show_alert=True)
        return

    inventory = await db.get_user_inventory(user_id)
    total_wheat = len(ready_plots) * WHEAT_HARVEST_AMOUNT
    if storage_used(inventory, SILO_ITEMS) + total_wheat > SILO_CAPACITY:
        await callback.answer("В силосе нет места для всего урожая.", show_alert=True)
        return

    harvested = 0
    for plot_num in ready_plots:
        crop_id = await db.harvest_plot(user_id, plot_num)
        if crop_id:
            harvested += WHEAT_HARVEST_AMOUNT

    if not harvested:
        await callback.answer("Не получилось собрать урожай.", show_alert=True)
        return

    await db.modify_inventory(user_id, WHEAT_ID, harvested)
    await db.add_harvest_stat(user_id, "зерно", harvested)
    xp_amount = harvested * WHEAT_XP_PER_ITEM
    _, level_alert = await add_xp_and_get_alert(db, user_id, xp_amount, "wheat_harvest")
    await callback.answer(f"Собрано: +{harvested} 🌾 пшеницы\n+{xp_amount} XP{level_alert}", show_alert=True)
    await cq_farm_view_plots(callback, FarmCallback(action="view_plots", owner_id=user_id), db)


@farm_router.callback_query(PlotCallback.filter(F.action == "plant_do"))
async def cq_plot_plant_do(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id):
        return
    user_id = callback.from_user.id
    crop_id = CROP_CODE_TO_ID.get(callback_data.crop_id or "w", WHEAT_ID)
    if crop_id != WHEAT_ID:
        await callback.answer("Сейчас доступна только пшеница.", show_alert=True)
        return

    active = get_active_plot_map(await db.get_user_plots(user_id))
    if callback_data.plot_num in active:
        await callback.answer("Это поле уже занято.", show_alert=True)
        return

    inventory = await db.get_user_inventory(user_id)
    if inventory.get(WHEAT_ID, 0) < WHEAT_PLANT_COST:
        await callback.answer("Не хватает 🌾 пшеницы для посадки.", show_alert=True)
        return

    if not await db.modify_inventory(user_id, WHEAT_ID, -WHEAT_PLANT_COST):
        await callback.answer("Не хватает 🌾 пшеницы для посадки.", show_alert=True)
        return

    ready_at = datetime.now() + timedelta(minutes=WHEAT_GROW_MINUTES)
    if not await db.plant_crop(user_id, callback_data.plot_num, WHEAT_ID, ready_at):
        await db.modify_inventory(user_id, WHEAT_ID, WHEAT_PLANT_COST)
        await callback.answer("Это поле уже занято.", show_alert=True)
        return

    await callback.answer(f"Посажена 🌾 пшеница. Рост: {WHEAT_GROW_MINUTES} мин.")
    await cq_farm_view_plots(callback, FarmCallback(action="view_plots", owner_id=user_id), db)


@farm_router.callback_query(PlotCallback.filter(F.action == "harvest"))
async def cq_plot_harvest(callback: CallbackQuery, callback_data: PlotCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id):
        return
    ok, message = await harvest_plot(callback.from_user.id, callback_data.plot_num, db)
    await callback.answer(message, show_alert=True)
    if ok:
        await cq_farm_view_plots(callback, FarmCallback(action="view_plots", owner_id=callback.from_user.id), db)


@farm_router.callback_query(PlotCallback.filter(F.action == "show_time"))
async def cq_plot_time(callback: CallbackQuery, callback_data: PlotCallback):
    if not await check_owner(callback, callback_data.owner_id):
        return
    await callback.answer("Пшеница ещё растёт.", show_alert=True)


@farm_router.callback_query(FarmCallback.filter(F.action == "animals"))
async def cq_farm_animals(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id):
        return
    text, keyboard = await get_animals_menu(callback.from_user.id, db)
    await edit_farm_message(callback, text, keyboard)
    await callback.answer()


@farm_router.callback_query(FarmCallback.filter(F.action == "collect_eggs"))
async def cq_farm_collect_eggs(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id):
        return
    user_id = callback.from_user.id
    farm = await db.get_user_farm_data(user_id)
    chicken_count = farm.get("chicken_count") or CHICKEN_COUNT
    timer_end = farm.get("chicken_timer_end")
    now = datetime.now()

    if not timer_end or now < timer_end:
        await callback.answer("Яйца ещё не готовы.", show_alert=True)
        return

    inventory = await db.get_user_inventory(user_id)
    if storage_used(inventory, BARN_ITEMS) + chicken_count > BARN_CAPACITY:
        await callback.answer("В амбаре нет места для яиц.", show_alert=True)
        return

    await db.modify_inventory(user_id, EGG_ID, chicken_count)
    xp_amount = chicken_count * EGG_XP_PER_ITEM
    _, level_alert = await add_xp_and_get_alert(db, user_id, xp_amount, "egg_collect")
    await db.set_chicken_timer(user_id, now + timedelta(minutes=EGG_PRODUCTION_MINUTES))
    await callback.answer(f"Собрано: +{chicken_count} 🥚 яиц\n+{xp_amount} XP{level_alert}", show_alert=True)
    text, keyboard = await get_animals_menu(user_id, db)
    await edit_farm_message(callback, text, keyboard)


@farm_router.callback_query(FarmCallback.filter(F.action == "barn"))
async def cq_farm_barn(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id):
        return
    text, keyboard = await get_barn_menu(callback.from_user.id, db)
    await edit_farm_message(callback, text, keyboard)
    await callback.answer()


@farm_router.callback_query(FarmCallback.filter(F.action == "silo"))
async def cq_farm_silo(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id):
        return
    text, keyboard = await get_silo_menu(callback.from_user.id, db)
    await edit_farm_message(callback, text, keyboard)
    await callback.answer()


@farm_router.callback_query(FarmCallback.filter(F.action == "production"))
async def cq_farm_production(callback: CallbackQuery, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data.owner_id):
        return
    text, keyboard = get_production_menu(callback.from_user.id)
    await edit_farm_message(callback, text, keyboard)
    await callback.answer()


@farm_router.callback_query(FarmCallback.filter(F.action == "storage_upgrade_info"))
async def cq_farm_storage_upgrade_info(callback: CallbackQuery, callback_data: FarmCallback):
    if not await check_owner(callback, callback_data.owner_id):
        return
    await callback.answer("Улучшения хранилищ добавим позже. Сейчас лимит 50/50.", show_alert=True)


@farm_router.callback_query(FarmCallback.filter(F.action == "orders_menu"))
async def cq_farm_orders_menu(callback: CallbackQuery, callback_data: FarmCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id):
        return
    text, keyboard = await get_orders_menu(callback.from_user.id, db)
    await edit_farm_message(callback, text, keyboard)
    await callback.answer()


@farm_router.callback_query(OrderCallback.filter(F.action == "complete"))
async def cq_farm_order_complete(callback: CallbackQuery, callback_data: OrderCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id):
        return
    user_id = callback.from_user.id
    current_order_id, next_order_time = await db.get_current_order(user_id)
    if next_order_time or current_order_id != callback_data.order_id:
        await callback.answer("Этот заказ уже устарел.", show_alert=True)
        return

    order = FARM_ORDER_POOL.get(current_order_id)
    if not order:
        await callback.answer("Заказ не найден.", show_alert=True)
        return

    inventory = await db.get_user_inventory(user_id)
    if not can_complete_order(order, inventory):
        await callback.answer("Не хватает ресурсов для заказа.", show_alert=True)
        return

    for item_id, amount in order["items"].items():
        if not await db.modify_inventory(user_id, item_id, -amount):
            await callback.answer("Не получилось списать ресурсы.", show_alert=True)
            return

    await db.change_rating(user_id, order["reward_amount"])
    _, level_alert = await add_xp_and_get_alert(db, user_id, order["reward_xp"], "farm_order")
    await db.complete_current_order(user_id, current_order_id, ORDER_COOLDOWN_MINUTES)

    await callback.answer(
        f"Заказ выполнен!\n+{order['reward_amount']} 🍺\n+{order['reward_xp']} XP{level_alert}",
        show_alert=True,
    )
    text, keyboard = await get_orders_menu(user_id, db)
    await edit_farm_message(callback, text, keyboard)

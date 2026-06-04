# handlers/shop.py
import logging
from contextlib import suppress

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData
from aiogram.exceptions import TelegramBadRequest

from database import Database
# ✅ Импортируем из нового farm.py (который выше)
from .farm import FarmCallback, check_owner, back_btn_to_farm
from .farm_config import SHOP_DAILY_LIMITS, SHOP_PRICES, FARM_ITEM_NAMES

shop_router = Router()

class ShopCallback(CallbackData, prefix="shop_buy"):
    action: str
    item_id: str
    quantity: int
    owner_id: int


def get_buy_buttons(item_id: str, icon: str, remaining: int, owner_id: int) -> list[InlineKeyboardButton]:
    buttons = []
    for quantity in (1, 5, 10):
        if remaining >= quantity:
            buttons.append(
                InlineKeyboardButton(
                    text=f"{icon} {quantity}",
                    callback_data=ShopCallback(
                        action="buy",
                        item_id=item_id,
                        quantity=quantity,
                        owner_id=owner_id
                    ).pack()
                )
            )
    return buttons


# --- МЕНЮ МАГАЗИНА (Твой стиль) ---
async def get_shop_menu(user_id: int, db: Database, owner_id: int) -> (str, InlineKeyboardMarkup):

    balance = await db.get_user_beer_rating(user_id)
    inventory = await db.get_user_inventory(user_id)

    # --- Зерно ---
    item_g = 'семя_зерна'
    price_g = SHOP_PRICES.get(item_g, 0)
    stock_g = inventory.get(item_g, 0)
    limit_g = SHOP_DAILY_LIMITS.get(item_g, 0)
    bought_g = await db.get_shop_purchase_count(user_id, item_g)
    remaining_g = max(0, limit_g - bought_g)

    # --- Хмель ---
    item_h = 'семя_хмеля'
    price_h = SHOP_PRICES.get(item_h, 0)
    stock_h = inventory.get(item_h, 0)
    limit_h = SHOP_DAILY_LIMITS.get(item_h, 0)
    bought_h = await db.get_shop_purchase_count(user_id, item_h)
    remaining_h = max(0, limit_h - bought_h)

    text = (
        f"🏪 <b>МАГАЗИН</b>\n"
        f"<code>══════════════════</code>\n"
        f"Баланс: <b>{balance} 🍺</b>\n"
        f"<code>══════════════════</code>\n\n"
        f"<i>Семена продаются дневным запасом, чтобы ферма не превращалась в бесконечную печатню.</i>\n\n"

        f"🌾 <b>{FARM_ITEM_NAMES[item_g]}</b>\n"
        f"• Цена: <code>{price_g} 🍺</code>\n"
        f"• На складе: <code>{stock_g} шт.</code>\n"
        f"• Сегодня: <code>{bought_g}/{limit_g}</code> куплено, осталось <code>{remaining_g}</code>"
    )

    kb = []
    grain_buttons = get_buy_buttons(item_g, "🌾", remaining_g, owner_id)
    if grain_buttons:
        kb.append(grain_buttons)

    text += (
        f"\n\n🌱 <b>{FARM_ITEM_NAMES[item_h]}</b>\n"
        f"• Цена: <code>{price_h} 🍺</code>\n"
        f"• На складе: <code>{stock_h} шт.</code>\n"
        f"• Сегодня: <code>{bought_h}/{limit_h}</code> куплено, осталось <code>{remaining_h}</code>"
    )

    hops_buttons = get_buy_buttons(item_h, "🌱", remaining_h, owner_id)
    if hops_buttons:
        kb.append(hops_buttons)

    # Кнопка Назад (Импортирована из farm.py, где FarmCallback теперь простой и работает)
    kb.append(back_btn_to_farm(user_id))

    return text, InlineKeyboardMarkup(inline_keyboard=kb)

# --- ХЭНДЛЕР ПОКУПКИ ---
@shop_router.callback_query(ShopCallback.filter(F.action == "buy"))
async def cq_shop_buy(callback: CallbackQuery, callback_data: ShopCallback, db: Database):
    if not await check_owner(callback, callback_data.owner_id):
        return

    user_id = callback.from_user.id
    item_id = callback_data.item_id
    quantity = callback_data.quantity

    price_per_one = SHOP_PRICES.get(item_id)
    if price_per_one is None:
        await callback.answer("⛔ Ошибка! Предмет не найден.", show_alert=True)
        return

    daily_limit = SHOP_DAILY_LIMITS.get(item_id)
    if daily_limit is not None:
        bought_today = await db.get_shop_purchase_count(user_id, item_id)
        remaining = max(0, daily_limit - bought_today)
        if quantity > remaining:
            await callback.answer(
                f"⛔ Дневной лимит.\nОсталось сегодня: {remaining} шт.",
                show_alert=True
            )
            return

    total_cost = price_per_one * quantity

    balance = await db.get_user_beer_rating(user_id)
    if balance < total_cost:
        await callback.answer(f"⛔ Недостаточно 🍺!\nНужно: {total_cost} 🍺", show_alert=True)
        return

    try:
        await db.change_rating(user_id, -total_cost)
        await db.modify_inventory(user_id, item_id, quantity)
        await db.add_shop_purchase(user_id, item_id, quantity)

        await callback.answer(f"✅ Куплено: +{quantity} {FARM_ITEM_NAMES[item_id]}", show_alert=False)

        # Обновляем меню
        text, keyboard = await get_shop_menu(user_id, db, callback_data.owner_id)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=keyboard)

    except Exception as e:
        logging.error(f"[Shop] Error: {e}")
        await callback.answer(f"⛔ Ошибка!", show_alert=True)

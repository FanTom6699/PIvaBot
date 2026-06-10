# handlers/farm_config.py
import random # ✅ НОВЫЙ ИМПОРТ

# --- КОДЫ ДЛЯ CALLBACK (Фикс 64 байт) ---
CROP_CODE_TO_ID = {
    "g": "семя_зерна", # g = grain (зерно)
    "h": "семя_хмеля", # h = hops (хмель)
}

# --- Короткие имена для UI ---
CROP_SHORT = {
    'зерно': "🌾 Зерно",
    'хмель': "🌱 Хмель",
}

# --- НАЗВАНИЯ ПРЕДМЕТОВ ---
FARM_ITEM_NAMES = {
    # Ресурсы
    'зерно': "🌾 Зерно",
    'хмель': "🌱 Хмель",
    'кукуруза': "🌽 Кукуруза",
    'яйца': "🥚 Яйца",
    'молоко': "🥛 Молоко",
    
    # Семена
    'семя_зерна': "Семена 🌾 Зерна",
    'семя_хмеля': "Семена 🌱 Хмеля",
}

BARN_BASE_CAPACITY = 100
BARN_DISPLAY_ITEMS = [
    ('зерно', "🌾 Ячмень"),
    ('хмель', "🍃 Хмель"),
    ('кукуруза', "🌽 Кукуруза"),
    ('яйца', "🥚 Яйца"),
    ('молоко', "🥛 Молоко"),
]
BARN_SEED_ITEMS = [
    ('семя_зерна', "🌾 Семена ячменя"),
    ('семя_хмеля', "🍃 Семена хмеля"),
]
FARM_SHOP_UNLOCKS = {
    "extra_plot": 2,
    "barn_upgrade": 3,
}

# --- ID Продукта -> ID Семени (Обратный словарь) ---
PRODUCT_TO_SEED_ID = {
    'зерно': 'семя_зерна',
    'хмель': 'семя_хмеля',
}

# --- ID Семени -> ID Продукта (Старый словарь, но нужен для Сбора) ---
SEED_TO_PRODUCT_ID = {
    'семя_зерна': 'зерно',
    'семя_хмеля': 'хмель',
}

# --- ПИВОВАРНЯ: ID Ресурса -> Количество для 1 варки ---
BREWERY_RECIPE = {
    'зерно': 5,
    'хмель': 3,
}

# --- Магазин (Твой сбалансированный) ---
SHOP_PRICES = {
    'семя_зерна': 1,
    'семя_хмеля': 3,
}
# (Себестоимость 1 варки: (5*1) + (3*3) = 14 🍺)
# --- ---

# --- Дневные лимиты магазина ---
SHOP_DAILY_LIMITS = {
    'семя_зерна': 20,
    'семя_хмеля': 10,
}

# --- ✅ СБАЛАНСИРОВАННЫЕ УЛУЧШЕНИЯ ПОЛЯ ✅ ---
FIELD_UPGRADES = {
    # Lvl: {cost, time_h, plots, chance_x2, grow_time_min: {зерно, хмель}}
    1: {'cost': 0,     'time_h': 0, 'plots': 2, 'chance_x2': 0,  'grow_time_min': {'зерно': 20, 'хмель': 40}},
    2: {'cost': 100,   'time_h': 1, 'plots': 2, 'chance_x2': 5,  'grow_time_min': {'зерно': 20, 'хмель': 40}},
    3: {'cost': 250,   'time_h': 2, 'plots': 3, 'chance_x2': 5,  'grow_time_min': {'зерно': 18, 'хмель': 35}}, 
    4: {'cost': 500,   'time_h': 3, 'plots': 3, 'chance_x2': 10, 'grow_time_min': {'зерно': 18, 'хмель': 35}},
    5: {'cost': 1000,  'time_h': 4, 'plots': 4, 'chance_x2': 10, 'grow_time_min': {'зерно': 15, 'хмель': 30}}, 
    6: {'cost': 2000,  'time_h': 5, 'plots': 4, 'chance_x2': 15, 'grow_time_min': {'зерно': 15, 'хмель': 30}},
    7: {'cost': 4000,  'time_h': 6, 'plots': 5, 'chance_x2': 15, 'grow_time_min': {'зерно': 12, 'хмель': 25}}, 
    8: {'cost': 7000,  'time_h': 8, 'plots': 5, 'chance_x2': 20, 'grow_time_min': {'зерно': 12, 'хмель': 25}},
    9: {'cost': 10000, 'time_h': 10, 'plots': 6, 'chance_x2': 25, 'grow_time_min': {'зерно': 10, 'хмель': 20}}, 
    10:{'cost': 15000, 'time_h': 12, 'plots': 6, 'chance_x2': 35, 'grow_time_min': {'зерно': 10, 'хмель': 20}},
}

# --- ✅ СБАЛАНСИРОВАННЫЕ УЛУЧШЕНИЯ ПИВОВАРНИ ✅ ---
BREWERY_UPGRADES = {
    # Lvl: {cost, time_h, reward, brew_time_min}
    1:     {'cost': 0,     'time_h': 0, 'reward': 35, 'brew_time_min': 30},
    2:     {'cost': 100,   'time_h': 1, 'reward': 40, 'brew_time_min': 25}, 
    3:     {'cost': 250,   'time_h': 2, 'reward': 48, 'brew_time_min': 20},
    4:     {'cost': 500,   'time_h': 3, 'reward': 55, 'brew_time_min': 18},
    5:     {'cost': 1000,  'time_h': 4, 'reward': 65, 'brew_time_min': 15},
    6:     {'cost': 2000,  'time_h': 5, 'reward': 75, 'brew_time_min': 12},
    7:     {'cost': 4000,  'time_h': 6, 'reward': 90, 'brew_time_min': 10},
    8:     {'cost': 7000,  'time_h': 8, 'reward': 110, 'brew_time_min': 8},
    9:     {'cost': 11000, 'time_h': 10,'reward': 130, 'brew_time_min': 6},
    10:    {'cost': 18000, 'time_h': 12,'reward': 150, 'brew_time_min': 5},
}
# --- --- ---

# --- ФУНКЦИЯ ДЛЯ УЛУЧШЕНИЙ ---
def get_level_data(level: int, upgrade_data: dict) -> dict:
    data = upgrade_data.get(level, {}).copy() 
    max_level_num = max(upgrade_data.keys())
    data['max_level'] = (level == max_level_num)
    if not data and level > max_level_num:
        data = upgrade_data.get(max_level_num, {}).copy()
        data['max_level'] = True
    if not data.get('max_level', False):
        next_level_data = upgrade_data.get(level + 1, {})
        data['next_cost'] = next_level_data.get('cost')
        data['next_time_h'] = next_level_data.get('time_h')
    return data

# --- ДОСКА ЗАКАЗОВ ---
# Заказы считаются так, чтобы игрок выбирал: сдать сырье бармену или пустить его в варку.
FARM_ORDER_POOL = {
    'grain_10': {
        'text': "Мешок солода: 10 🌾 Зерна",
        'items': {'зерно': 10},
        'reward_type': 'beer', 'reward_amount': 25
    },
    'grain_25': {
        'text': "Поставка к стойке: 16 🌾 Зерна",
        'items': {'зерно': 16},
        'reward_type': 'beer', 'reward_amount': 46
    },
    'hops_6': {
        'text': "Ароматная партия: 6 🌱 Хмеля",
        'items': {'хмель': 6},
        'reward_type': 'beer', 'reward_amount': 38
    },
    'hops_15': {
        'text': "Хмельной запас: 8 🌱 Хмеля",
        'items': {'хмель': 8},
        'reward_type': 'beer', 'reward_amount': 54
    },
    'brew_1': {
        'text': "Набор для варки: 5 🌾 + 3 🌱",
        'items': {'зерно': 5, 'хмель': 3},
        'reward_type': 'beer', 'reward_amount': 42
    },
    'brew_2': {
        'text': "Двойная варка: 10 🌾 + 6 🌱",
        'items': {'зерно': 10, 'хмель': 6},
        'reward_type': 'beer', 'reward_amount': 90
    },
    'brew_big': {
        'text': "Большой вечер: 15 🌾 + 9 🌱",
        'items': {'зерно': 15, 'хмель': 9},
        'reward_type': 'beer', 'reward_amount': 135
    },
    'starter_grain': {
        'text': "Вернуть семена: 5 семян 🌾",
        'items': {'семя_зерна': 5},
        'reward_type': 'beer', 'reward_amount': 12
    },
    'starter_hops': {
        'text': "Вернуть семена: 3 семени 🌱",
        'items': {'семя_хмеля': 3},
        'reward_type': 'beer', 'reward_amount': 12
    }
}

ORDER_DAILY_BUDGET = {
    'зерно': 20,
    'хмель': 10,
    'семя_зерна': 10,
    'семя_хмеля': 5,
}


def _order_fits_budget(order_id: str, used: dict) -> bool:
    order = FARM_ORDER_POOL[order_id]
    for item_id, amount in order.get('items', {}).items():
        if used.get(item_id, 0) + amount > ORDER_DAILY_BUDGET.get(item_id, amount):
            return False
    return True


def _add_order_to_budget(order_id: str, used: dict):
    order = FARM_ORDER_POOL[order_id]
    for item_id, amount in order.get('items', {}).items():
        used[item_id] = used.get(item_id, 0) + amount


def get_random_orders(count=3) -> list:
    """Возвращает N заказов так, чтобы общий набор не спорил с дневным лимитом магазина."""
    order_keys = list(FARM_ORDER_POOL.keys())
    random.shuffle(order_keys)

    selected = []
    used = {}
    for order_id in order_keys:
        if len(selected) >= count:
            break
        if _order_fits_budget(order_id, used):
            selected.append(order_id)
            _add_order_to_budget(order_id, used)

    if len(selected) < count:
        easy_orders = sorted(
            order_keys,
            key=lambda oid: sum(FARM_ORDER_POOL[oid].get('items', {}).values())
        )
        for order_id in easy_orders:
            if len(selected) >= count:
                break
            if order_id not in selected and _order_fits_budget(order_id, used):
                selected.append(order_id)
                _add_order_to_budget(order_id, used)

    return selected[:count]
# --- --- ---

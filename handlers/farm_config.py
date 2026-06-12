import random

WHEAT_ID = "пшеница"
EGG_ID = "яйца"

START_FIELD_COUNT = 6
START_WHEAT_AMOUNT = 6
CHICKEN_COUNT = 2
CHICKEN_MAX_COUNT = 2
CHICKEN_FEED_ITEM_ID = WHEAT_ID
CHICKEN_FEED_COST = 1

WHEAT_GROW_MINUTES = 2
WHEAT_PLANT_COST = 1
WHEAT_HARVEST_AMOUNT = 2
WHEAT_XP_PER_ITEM = 1

EGG_PRODUCTION_MINUTES = 20
EGG_XP_PER_ITEM = 2

SILO_CAPACITY = 50
BARN_CAPACITY = 50
ORDER_COOLDOWN_MINUTES = 30

CROP_CODE_TO_ID = {
    "w": WHEAT_ID,
    "g": WHEAT_ID,
}

CROP_SHORT = {
    WHEAT_ID: "🌾 Пшеница",
    "зерно": "🌾 Пшеница",
    "хмель": "🍃 Хмель",
}

FARM_ITEM_NAMES = {
    WHEAT_ID: "🌾 Пшеница",
    EGG_ID: "🥚 Яйца",
    "зерно": "🌾 Зерно",
    "хмель": "🍃 Хмель",
    "кукуруза": "🌽 Кукуруза",
    "молоко": "🥛 Молоко",
}

SILO_ITEMS = [
    (WHEAT_ID, "🌾 Пшеница"),
]

BARN_ITEMS = [
    (EGG_ID, "🥚 Яйца"),
]

BARN_BASE_CAPACITY = BARN_CAPACITY
BARN_DISPLAY_ITEMS = BARN_ITEMS
FARM_SHOP_UNLOCKS = {"barn_upgrade": 3}

SEED_TO_PRODUCT_ID = {
    "семя_зерна": WHEAT_ID,
    "семя_хмеля": WHEAT_ID,
    "зерно": WHEAT_ID,
    "хмель": WHEAT_ID,
    WHEAT_ID: WHEAT_ID,
}

BREWERY_RECIPE = {
    "зерно": 5,
    "хмель": 3,
}

FIELD_UPGRADES = {
    1: {"cost": 0, "time_h": 0, "plots": START_FIELD_COUNT, "chance_x2": 0, "grow_time_min": {WHEAT_ID: WHEAT_GROW_MINUTES}},
}

BREWERY_UPGRADES = {
    1: {"cost": 0, "time_h": 0, "reward": 35, "brew_time_min": 30},
}


def get_level_data(level: int, upgrade_data: dict) -> dict:
    data = upgrade_data.get(level, {}).copy()
    max_level_num = max(upgrade_data.keys())
    data["max_level"] = level >= max_level_num
    if not data and level > max_level_num:
        data = upgrade_data.get(max_level_num, {}).copy()
        data["max_level"] = True
    return data


FARM_ORDER_POOL = {
    "baker": {
        "title": "Пекарь",
        "items": {WHEAT_ID: 3},
        "reward_amount": 6,
        "reward_xp": 3,
    },
    "farmer": {
        "title": "Фермер",
        "items": {WHEAT_ID: 5},
        "reward_amount": 10,
        "reward_xp": 5,
    },
    "tavern": {
        "title": "Таверна",
        "items": {EGG_ID: 1},
        "reward_amount": 5,
        "reward_xp": 2,
    },
    "breakfast": {
        "title": "Завтрак",
        "items": {EGG_ID: 2},
        "reward_amount": 10,
        "reward_xp": 5,
    },
    "market": {
        "title": "Рынок",
        "items": {WHEAT_ID: 4},
        "reward_amount": 8,
        "reward_xp": 4,
    },
    "neighbor": {
        "title": "Сосед",
        "items": {WHEAT_ID: 2, EGG_ID: 1},
        "reward_amount": 8,
        "reward_xp": 4,
    },
    "bartender": {
        "title": "Бармен",
        "items": {WHEAT_ID: 6},
        "reward_amount": 12,
        "reward_xp": 6,
    },
    "cafe": {
        "title": "Кафе",
        "items": {WHEAT_ID: 8},
        "reward_amount": 18,
        "reward_xp": 8,
    },
    "inn": {
        "title": "Трактир",
        "items": {EGG_ID: 3},
        "reward_amount": 15,
        "reward_xp": 7,
    },
    "canteen": {
        "title": "Столовая",
        "items": {WHEAT_ID: 5, EGG_ID: 2},
        "reward_amount": 18,
        "reward_xp": 8,
    },
    "hotel": {
        "title": "Гостиница",
        "items": {WHEAT_ID: 10},
        "reward_amount": 22,
        "reward_xp": 10,
    },
    "traveler": {
        "title": "Путник",
        "items": {WHEAT_ID: 7, EGG_ID: 2},
        "reward_amount": 20,
        "reward_xp": 9,
    },
    "caravan": {
        "title": "Караван",
        "items": {EGG_ID: 4},
        "reward_amount": 22,
        "reward_xp": 10,
    },
    "fair": {
        "title": "Ярмарка",
        "items": {WHEAT_ID: 12},
        "reward_amount": 25,
        "reward_xp": 12,
    },
    "harvest_festival": {
        "title": "Праздник урожая",
        "items": {WHEAT_ID: 10, EGG_ID: 4},
        "reward_amount": 35,
        "reward_xp": 15,
    },
    "big_breakfast": {
        "title": "Большой завтрак",
        "items": {EGG_ID: 6},
        "reward_amount": 35,
        "reward_xp": 15,
    },
    "royal_kitchen": {
        "title": "Королевская кухня",
        "items": {WHEAT_ID: 15},
        "reward_amount": 40,
        "reward_xp": 18,
    },
    "baron_tavern": {
        "title": "Таверна барона",
        "items": {WHEAT_ID: 12, EGG_ID: 5},
        "reward_amount": 45,
        "reward_xp": 20,
    },
    "village_feast": {
        "title": "Сельский пир",
        "items": {WHEAT_ID: 18, EGG_ID: 3},
        "reward_amount": 50,
        "reward_xp": 22,
    },
    "elder_order": {
        "title": "Заказ старосты",
        "items": {WHEAT_ID: 20, EGG_ID: 6},
        "reward_amount": 60,
        "reward_xp": 25,
    },
}


def get_random_order() -> str:
    return random.choice(list(FARM_ORDER_POOL.keys()))


def get_random_orders(count=1) -> list[str]:
    order_keys = list(FARM_ORDER_POOL.keys())
    random.shuffle(order_keys)
    return order_keys[:count]

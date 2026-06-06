# database.py
import aiosqlite
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple

# --- КОНСТАНТЫ ---
DEFAULT_INVENTORY = {
    'зерно': 0, 'хмель': 0,
    'семя_зерна': 5, 'семя_хмеля': 3
}

class Database:
    def __init__(self, db_name='bot_database.db'):
        self.db_name = db_name

    async def initialize(self):
        logging.info("Инициализация базы данных...")
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            # --- ОСНОВНЫЕ ТАБЛИЦЫ ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    last_name TEXT,
                    username TEXT,
                    beer_rating INTEGER DEFAULT 0,
                    last_beer_time TEXT,
                    created_at TEXT
                )
            ''')
            await self._ensure_column(db, "users", "created_at", "TEXT")
            await db.execute(
                "UPDATE users SET created_at = ? WHERE created_at IS NULL",
                (datetime.now().isoformat(),)
            )
            await db.execute('CREATE TABLE IF NOT EXISTS chats (chat_id INTEGER PRIMARY KEY, title TEXT)')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS chat_members (
                    chat_id INTEGER,
                    user_id INTEGER,
                    first_seen_at TEXT,
                    PRIMARY KEY (chat_id, user_id)
                )
            ''')
            await db.execute('CREATE TABLE IF NOT EXISTS game_data (key TEXT PRIMARY KEY, value INTEGER)')
            # --- ТАБЛИЦЫ ФЕРМЫ ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_farm_data (
                    user_id INTEGER PRIMARY KEY,
                    field_level INTEGER DEFAULT 1,
                    brewery_level INTEGER DEFAULT 1,
                    brewery_batch_size INTEGER DEFAULT 0,
                    brewery_batch_timer_end TEXT,
                    field_upgrade_timer_end TEXT,
                    brewery_upgrade_timer_end TEXT
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_plots (
                    user_id INTEGER,
                    plot_number INTEGER,
                    crop_id TEXT,
                    ready_time TEXT,
                    PRIMARY KEY (user_id, plot_number)
                )
            ''')
            # Инвентарь (JSON)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_inventory (
                    user_id INTEGER PRIMARY KEY,
                    items_json TEXT DEFAULT '{}'
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_harvest_stats (
                    user_id INTEGER PRIMARY KEY,
                    total_grain INTEGER DEFAULT 0,
                    total_hops INTEGER DEFAULT 0
                )
            ''')
            # Уведомления
            await db.execute('''
                CREATE TABLE IF NOT EXISTS farm_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    task_type TEXT, 
                    data_json TEXT, 
                    is_sent INTEGER DEFAULT 0
                )
            ''')
            
            # --- ✅ ТАБЛИЦА: ЗАКАЗЫ (ORDERS) ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_orders (
                    user_id INTEGER,
                    slot_id INTEGER, -- 1, 2 или 3
                    order_id TEXT,   -- ID заказа из конфига (например, 'grain_10')
                    is_completed INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, slot_id)
                )
            ''')
            # Таблица для таймера сброса заказов (раз в 24ч)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_orders_meta (
                    user_id INTEGER PRIMARY KEY,
                    last_reset_time TEXT
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_shop_purchases (
                    user_id INTEGER,
                    item_id TEXT,
                    bought_count INTEGER DEFAULT 0,
                    purchase_date TEXT,
                    PRIMARY KEY (user_id, item_id)
                )
            ''')

            # --- ТАБЛИЦА МАФИИ ---
            await db.execute('''
                CREATE TABLE IF NOT EXISTS mafia_games (
                    chat_id INTEGER PRIMARY KEY,
                    message_id INTEGER,
                    creator_id INTEGER,
                    status TEXT, 
                    start_time TEXT,
                    timer_task_id TEXT
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS mafia_players (
                    chat_id INTEGER,
                    user_id INTEGER,
                    role TEXT,
                    is_alive INTEGER DEFAULT 1,
                    is_healed INTEGER DEFAULT 0,
                    is_checked INTEGER DEFAULT 0,
                    votes INTEGER DEFAULT 0,
                    PRIMARY KEY (chat_id, user_id)
                )
            ''')
            
            # Настройки по умолчанию
            default_settings = [
                ('beer_cooldown', 7200), ('jackpot_chance', 100),
                ('roulette_cooldown', 300), ('roulette_min_bet', 10), ('roulette_max_bet', 1000),
                ('ladder_min_bet', 10), ('ladder_max_bet', 500),
                ('mafia_min_players', 4), ('mafia_max_players', 12),
                ('mafia_lobby_timer', 60), ('mafia_night_timer', 60),
                ('mafia_day_timer', 120), ('mafia_vote_timer', 60),
                ('mafia_win_reward', 100), ('mafia_lose_reward', 10),
                ('mafia_win_authority', 5), ('mafia_lose_authority', 1)
            ]
            for key, value in default_settings:
                await db.execute('INSERT OR IGNORE INTO game_data (key, value) VALUES (?, ?)', (key, value))
            
            await db.commit()
            logging.info("БД инициализирована.")

    # --- ОБЩИЕ МЕТОДЫ ---

    async def _ensure_column(self, db: aiosqlite.Connection, table: str, column: str, column_type: str):
        cursor = await db.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in await cursor.fetchall()]
        if column not in columns:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    async def user_exists(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
            return await cursor.fetchone() is not None

    async def add_user(self, user_id: int, first_name: str, last_name: str, username: str):
        async with aiosqlite.connect(self.db_name) as db:
            now_iso = datetime.now().isoformat()
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, first_name, last_name, username, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, first_name, last_name, username, now_iso)
            )
            await db.execute(
                "UPDATE users SET first_name = ?, last_name = ?, username = ? WHERE user_id = ?",
                (first_name, last_name, username, user_id)
            )
            # Инициализация фермы
            await db.execute("INSERT OR IGNORE INTO user_farm_data (user_id) VALUES (?)", (user_id,))
            # Инициализация инвентаря
            await db.execute(
                "INSERT OR IGNORE INTO user_inventory (user_id, items_json) VALUES (?, ?)",
                (user_id, json.dumps(DEFAULT_INVENTORY))
            )
            await db.execute("INSERT OR IGNORE INTO user_harvest_stats (user_id) VALUES (?)", (user_id,))
            await db.commit()

    async def add_chat(self, chat_id: int, title: str | None):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "INSERT OR REPLACE INTO chats (chat_id, title) VALUES (?, ?)",
                (chat_id, title)
            )
            await db.commit()

    async def remove_chat(self, chat_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
            await db.commit()

    async def add_user_to_chat(self, chat_id: int, user_id: int, title: str | None = None):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "INSERT OR REPLACE INTO chats (chat_id, title) VALUES (?, ?)",
                (chat_id, title)
            )
            await db.execute(
                "INSERT OR IGNORE INTO chat_members (chat_id, user_id, first_seen_at) VALUES (?, ?, ?)",
                (chat_id, user_id, datetime.now().isoformat())
            )
            await db.commit()

    async def get_user_chats(self, user_id: int, limit: int = 20):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT C.chat_id, C.title
                FROM chat_members M
                JOIN chats C ON C.chat_id = M.chat_id
                WHERE M.user_id = ?
                ORDER BY C.title COLLATE NOCASE
                LIMIT ?
                """,
                (user_id, limit)
            )
            return await cursor.fetchall()

    async def get_user_chat(self, user_id: int, chat_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT C.chat_id, C.title
                FROM chat_members M
                JOIN chats C ON C.chat_id = M.chat_id
                WHERE M.user_id = ? AND M.chat_id = ?
                """,
                (user_id, chat_id)
            )
            return await cursor.fetchone()

    async def get_all_users_ids(self) -> List[int]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT user_id FROM users")
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_user_by_id(self, user_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT user_id, first_name FROM users WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            return (row[0], row[1]) if row else None

    async def get_user_by_username(self, username: str):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT user_id, first_name FROM users WHERE lower(username) = lower(?)",
                (username,)
            )
            row = await cursor.fetchone()
            return (row[0], row[1]) if row else None

    async def get_user_profile(self, user_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT first_name, last_name, username, beer_rating, last_beer_time, created_at FROM users WHERE user_id = ?",
                (user_id,)
            )
            return await cursor.fetchone()

    async def get_user_beer_rating(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT beer_rating FROM users WHERE user_id = ?", (user_id,))
            result = await cursor.fetchone()
            return result[0] if result else 0

    # --- ИЗМЕНЕНИЕ РЕЙТИНГА И ВРЕМЕНИ ---
    
    async def change_rating(self, user_id: int, amount: int):
        """Изменяет рейтинг пользователя на amount (может быть отрицательным)."""
        async with aiosqlite.connect(self.db_name) as db:
            # Получаем текущий рейтинг
            cursor = await db.execute("SELECT beer_rating FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            current_rating = row[0] if row else 0
            
            new_rating = current_rating + amount
            if new_rating < 0: new_rating = 0 # Не уходим в минус
            
            await db.execute("UPDATE users SET beer_rating = ? WHERE user_id = ?", (new_rating, user_id))
            await db.commit()
            return new_rating

    async def update_last_beer_time(self, user_id: int):
        """Обновляет время последнего использования /beer."""
        now_iso = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("UPDATE users SET last_beer_time = ? WHERE user_id = ?", (now_iso, user_id))
            await db.commit()

    async def get_last_beer_time(self, user_id: int) -> datetime | None:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT last_beer_time FROM users WHERE user_id = ?", (user_id,))
            result = await cursor.fetchone()
            if result and result[0]:
                return datetime.fromisoformat(result[0])
            return None

    async def get_top_users(self, limit: int = 10):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT user_id, first_name, last_name, beer_rating FROM users ORDER BY beer_rating DESC LIMIT ?",
                (limit,)
            )
            return await cursor.fetchall()

    async def get_user_rank(self, user_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT beer_rating FROM users WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return None

            rating = row[0]
            cursor = await db.execute(
                "SELECT COUNT(*) + 1 FROM users WHERE beer_rating > ?",
                (rating,)
            )
            rank_row = await cursor.fetchone()
            return {
                "rank": rank_row[0] if rank_row else 1,
                "rating": rating,
            }

    async def get_chat_top_users(self, chat_id: int, limit: int = 10):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT U.user_id, U.first_name, U.last_name, U.beer_rating
                FROM chat_members M
                JOIN users U ON U.user_id = M.user_id
                WHERE M.chat_id = ?
                ORDER BY U.beer_rating DESC
                LIMIT ?
                """,
                (chat_id, limit)
            )
            return await cursor.fetchall()

    async def get_user_chat_rank(self, user_id: int, chat_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT U.beer_rating
                FROM users U
                JOIN chat_members M ON M.user_id = U.user_id
                WHERE U.user_id = ? AND M.chat_id = ?
                """,
                (user_id, chat_id)
            )
            row = await cursor.fetchone()
            if not row:
                return None

            rating = row[0]
            cursor = await db.execute(
                """
                SELECT COUNT(*) + 1
                FROM chat_members M
                JOIN users U ON U.user_id = M.user_id
                WHERE M.chat_id = ? AND U.beer_rating > ?
                """,
                (chat_id, rating)
            )
            rank_row = await cursor.fetchone()
            return {
                "rank": rank_row[0] if rank_row else 1,
                "rating": rating,
            }

    async def add_harvest_stat(self, user_id: int, product_id: str, amount: int):
        column_by_product = {
            "зерно": "total_grain",
            "хмель": "total_hops",
        }
        column = column_by_product.get(product_id)
        if not column:
            return

        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR IGNORE INTO user_harvest_stats (user_id) VALUES (?)", (user_id,))
            await db.execute(
                f"UPDATE user_harvest_stats SET {column} = {column} + ? WHERE user_id = ?",
                (amount, user_id)
            )
            await db.commit()

    async def get_top_harvest(self, product_id: str, limit: int = 10):
        column_by_product = {
            "зерно": "total_grain",
            "хмель": "total_hops",
        }
        column = column_by_product.get(product_id)
        if not column:
            return []

        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                f"""
                SELECT U.user_id, U.first_name, U.last_name, COALESCE(S.{column}, 0) AS total
                FROM users U
                LEFT JOIN user_harvest_stats S ON U.user_id = S.user_id
                WHERE COALESCE(S.{column}, 0) > 0
                ORDER BY total DESC
                LIMIT ?
                """,
                (limit,)
            )
            return await cursor.fetchall()

    async def get_user_harvest_rank(self, user_id: int, product_id: str):
        column_by_product = {
            "зерно": "total_grain",
            "хмель": "total_hops",
        }
        column = column_by_product.get(product_id)
        if not column:
            return None

        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR IGNORE INTO user_harvest_stats (user_id) VALUES (?)", (user_id,))
            cursor = await db.execute(
                f"SELECT COALESCE({column}, 0) FROM user_harvest_stats WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            total = row[0] if row else 0
            cursor = await db.execute(
                f"SELECT COUNT(*) + 1 FROM user_harvest_stats WHERE COALESCE({column}, 0) > ?",
                (total,)
            )
            rank_row = await cursor.fetchone()
            await db.commit()
            return {
                "rank": rank_row[0] if rank_row else 1,
                "total": total,
            }

    # --- НАСТРОЙКИ ---
    
    async def get_setting(self, key: str) -> int | None:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT value FROM game_data WHERE key = ?", (key,))
            result = await cursor.fetchone()
            return result[0] if result else None

    async def get_all_settings(self) -> Dict[str, int]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT key, value FROM game_data")
            rows = await cursor.fetchall()
            return {key: value for key, value in rows}

    async def update_setting(self, key: str, value: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR REPLACE INTO game_data (key, value) VALUES (?, ?)", (key, value))
            await db.commit()

    # --- ДЖЕКПОТ ---
    async def get_jackpot(self) -> int:
        return await self.get_setting("jackpot_value") or 0

    async def reset_jackpot(self):
        await self.update_setting("jackpot_value", 0)

    async def increase_jackpot(self, amount: int):
        current = await self.get_jackpot()
        await self.update_setting("jackpot_value", current + amount)
    # --- 🕵️ МАФИЯ (ВОССТАНОВЛЕНЫ) ---
    
    async def get_mafia_game(self, chat_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT * FROM mafia_games WHERE chat_id = ?", (chat_id,))
            return await cursor.fetchone()
            
    async def get_mafia_players(self, chat_id: int):
         async with aiosqlite.connect(self.db_name) as db:
             cursor = await db.execute("SELECT user_id, role, is_alive FROM mafia_players WHERE chat_id = ?", (chat_id,))
             return await cursor.fetchall()

    async def get_mafia_player_count(self, chat_id: int):
         async with aiosqlite.connect(self.db_name) as db:
             cursor = await db.execute("SELECT COUNT(*) FROM mafia_players WHERE chat_id = ?", (chat_id,))
             res = await cursor.fetchone()
             return res[0] if res else 0

    async def create_mafia_game(self, chat_id: int, message_id: int, creator_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR REPLACE INTO mafia_games (chat_id, message_id, creator_id, status) VALUES (?, ?, ?, 'lobby')", (chat_id, message_id, creator_id))
            await db.commit()
            
    async def join_mafia(self, chat_id: int, user_id: int):
        async with aiosqlite.connect(self.db_name) as db:
             await db.execute("INSERT OR IGNORE INTO mafia_players (chat_id, user_id, is_alive) VALUES (?, ?, 1)", (chat_id, user_id))
             await db.commit()

    async def end_mafia_game(self, chat_id: int):
         async with aiosqlite.connect(self.db_name) as db:
             await db.execute("DELETE FROM mafia_games WHERE chat_id = ?", (chat_id,))
             await db.execute("DELETE FROM mafia_players WHERE chat_id = ?", (chat_id,))
             await db.commit()

    # --- 🌾 ФЕРМА (ОСНОВНОЕ) ---

    async def get_user_farm_data(self, user_id: int) -> Dict[str, Any]:
        async with aiosqlite.connect(self.db_name) as db:
            # Убедимся, что запись существует
            await db.execute("INSERT OR IGNORE INTO user_farm_data (user_id) VALUES (?)", (user_id,))
            await db.commit()
            
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM user_farm_data WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            
            if not row: return {}

            data = dict(row)
            # Конвертируем строки дат в datetime
            for key in ['brewery_batch_timer_end', 'field_upgrade_timer_end', 'brewery_upgrade_timer_end']:
                if data.get(key):
                    try:
                        data[key] = datetime.fromisoformat(data[key])
                    except:
                        data[key] = None
            return data

    async def get_user_plots(self, user_id: int) -> List[Tuple]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT plot_number, crop_id, ready_time FROM user_plots WHERE user_id = ?", (user_id,))
            return await cursor.fetchall()

    async def get_user_inventory(self, user_id: int) -> Dict[str, int]:
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT items_json FROM user_inventory WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if row and row[0]:
                inventory = DEFAULT_INVENTORY.copy()
                inventory.update(json.loads(row[0]))
                return inventory
            return DEFAULT_INVENTORY.copy()

    async def modify_inventory(self, user_id: int, item_id: str, amount: int) -> bool:
        """Изменяет кол-во предмета. Возвращает False, если предмета не хватает."""
        inv = await self.get_user_inventory(user_id)
        current_qty = inv.get(item_id, 0)
        
        if current_qty + amount < 0:
            return False
        
        inv[item_id] = current_qty + amount
        
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "INSERT OR REPLACE INTO user_inventory (user_id, items_json) VALUES (?, ?)", 
                (user_id, json.dumps(inv))
            )
            await db.commit()
        return True

    async def get_shop_purchase_count(self, user_id: int, item_id: str, today: str | None = None) -> int:
        today = today or datetime.now().date().isoformat()
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT bought_count, purchase_date FROM user_shop_purchases WHERE user_id = ? AND item_id = ?",
                (user_id, item_id)
            )
            row = await cursor.fetchone()
            if not row:
                return 0

            bought_count, purchase_date = row
            if purchase_date != today:
                await db.execute(
                    "UPDATE user_shop_purchases SET bought_count = 0, purchase_date = ? WHERE user_id = ? AND item_id = ?",
                    (today, user_id, item_id)
                )
                await db.commit()
                return 0

            return bought_count or 0

    async def add_shop_purchase(self, user_id: int, item_id: str, quantity: int, today: str | None = None):
        today = today or datetime.now().date().isoformat()
        current_count = await self.get_shop_purchase_count(user_id, item_id, today)
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO user_shop_purchases (user_id, item_id, bought_count, purchase_date)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, item_id, current_count + quantity, today)
            )
            await db.commit()

    # --- ФЕРМА (ДЕЙСТВИЯ) ---

    async def plant_crop(self, user_id: int, plot_num: int, crop_id: str, ready_time: datetime) -> bool:
        try:
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute(
                    "INSERT INTO user_plots (user_id, plot_number, crop_id, ready_time) VALUES (?, ?, ?, ?)",
                    (user_id, plot_num, crop_id, ready_time.isoformat())
                )
                await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def harvest_plot(self, user_id: int, plot_num: int) -> str | None:
        """Удаляет растение с грядки и возвращает его crop_id (семя)."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT crop_id, ready_time FROM user_plots WHERE user_id = ? AND plot_number = ?", 
                (user_id, plot_num)
            )
            row = await cursor.fetchone()
            
            if not row: return None
            
            ready_time_str = row[1]
            if ready_time_str:
                 if datetime.now() < datetime.fromisoformat(ready_time_str):
                     return None # Еще не выросло

            await db.execute("DELETE FROM user_plots WHERE user_id = ? AND plot_number = ?", (user_id, plot_num))
            await db.commit()
            return row[0]

    async def start_brewing(self, user_id: int, batch_size: int, end_time: datetime):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "UPDATE user_farm_data SET brewery_batch_size = ?, brewery_batch_timer_end = ? WHERE user_id = ?",
                (batch_size, end_time.isoformat(), user_id)
            )
            # Добавляем уведомление
            await db.execute(
                "INSERT INTO farm_notifications (user_id, task_type, data_json) VALUES (?, ?, ?)",
                (user_id, 'batch', str(batch_size))
            )
            await db.commit()

    async def collect_brewery(self, user_id: int, reward_amount: int):
        """Сбор пива: сброс таймера и начисление рейтинга."""
        await self.change_rating(user_id, reward_amount)
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                "UPDATE user_farm_data SET brewery_batch_size = 0, brewery_batch_timer_end = NULL WHERE user_id = ?",
                (user_id,)
            )
            await db.commit()

    async def start_upgrade(self, user_id: int, building: str, end_time: datetime, cost: int):
        """Запуск улучшения (building = 'field' или 'brewery')."""
        if building not in {"field", "brewery"}:
            raise ValueError("Unknown upgrade building")

        # Списание средств
        await self.change_rating(user_id, -cost)

        level_col = f"{building}_level"
        col_name = f"{building}_upgrade_timer_end"
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                f"SELECT {level_col} FROM user_farm_data WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            next_level = (row[0] if row else 1) + 1

            await db.execute(
                f"UPDATE user_farm_data SET {col_name} = ? WHERE user_id = ?",
                (end_time.isoformat(), user_id)
            )
            # Добавляем уведомление
            await db.execute(
                "INSERT INTO farm_notifications (user_id, task_type, data_json) VALUES (?, ?, ?)",
                (user_id, f"{building}_upgrade", str(next_level))
            )
            await db.commit()

    async def finish_upgrade(self, user_id: int, building: str):
        """Применяет улучшение (повышает уровень). Вызывается Updater'ом."""
        level_col = f"{building}_level"
        timer_col = f"{building}_upgrade_timer_end"
        
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                f"UPDATE user_farm_data SET {level_col} = {level_col} + 1, {timer_col} = NULL WHERE user_id = ?",
                (user_id,)
            )
            await db.commit()

    # --- ✅ ЗАКАЗЫ (ORDERS) ---

    async def check_and_reset_orders(self, user_id: int):
        """Проверяет, прошло ли 24 часа. Если да - удаляет старые заказы."""
        from handlers.farm_config import FARM_ORDER_POOL, get_random_orders # Импорт внутри, чтобы избежать цикличности
        
        now = datetime.now()
        
        async with aiosqlite.connect(self.db_name) as db:
            # Получаем время последнего сброса
            cursor = await db.execute("SELECT last_reset_time FROM user_orders_meta WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            
            need_reset = False
            if not row:
                need_reset = True
            else:
                last_reset = datetime.fromisoformat(row[0])
                if now - last_reset > timedelta(hours=24):
                    need_reset = True

            if not need_reset:
                cursor = await db.execute("SELECT order_id FROM user_orders WHERE user_id = ?", (user_id,))
                current_orders = await cursor.fetchall()
                if len(current_orders) < 3 or any(order_id not in FARM_ORDER_POOL for (order_id,) in current_orders):
                    need_reset = True
            
            if need_reset:
                # Удаляем старые
                await db.execute("DELETE FROM user_orders WHERE user_id = ?", (user_id,))
                
                # Генерируем новые (3 шт)
                new_order_ids = get_random_orders(3)
                for i, order_id in enumerate(new_order_ids):
                    slot_id = i + 1
                    await db.execute(
                        "INSERT INTO user_orders (user_id, slot_id, order_id, is_completed) VALUES (?, ?, ?, 0)",
                        (user_id, slot_id, order_id)
                    )
                
                # Обновляем время сброса
                await db.execute(
                    "INSERT OR REPLACE INTO user_orders_meta (user_id, last_reset_time) VALUES (?, ?)",
                    (user_id, now.isoformat())
                )
                await db.commit()

    async def get_user_orders(self, user_id: int) -> List[Tuple[int, str, int]]:
        """Возвращает список: [(slot_id, order_id, is_completed), ...]"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT slot_id, order_id, is_completed FROM user_orders WHERE user_id = ? ORDER BY slot_id ASC", 
                (user_id,)
            )
            return await cursor.fetchall()

    async def complete_order(self, user_id: int, slot_id: int) -> bool:
        """Помечает заказ выполненным. Возвращает False, если уже выполнен."""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT is_completed FROM user_orders WHERE user_id = ? AND slot_id = ?", 
                (user_id, slot_id)
            )
            row = await cursor.fetchone()
            if not row or row[0] == 1:
                return False
                
            await db.execute(
                "UPDATE user_orders SET is_completed = 1 WHERE user_id = ? AND slot_id = ?", 
                (user_id, slot_id)
            )
            await db.commit()
            return True

    # --- УВЕДОМЛЕНИЯ И ЗАДАЧИ ---
    
    async def get_pending_notifications(self, now: datetime | None = None):
        """Возвращает список задач, время которых пришло."""
        now = now or datetime.now()
        async with aiosqlite.connect(self.db_name) as db:
            # Собираем задачи улучшений
            cursor_field = await db.execute(
                "SELECT T1.user_id, T1.task_type, T1.data_json FROM farm_notifications T1 "
                "JOIN user_farm_data T2 ON T1.user_id = T2.user_id "
                "WHERE T1.task_type = 'field_upgrade' AND T1.is_sent = 0 AND T2.field_upgrade_timer_end <= ?",
                (now.isoformat(),)
            )
            field_tasks = await cursor_field.fetchall()
            
            cursor_brewery = await db.execute(
                "SELECT T1.user_id, T1.task_type, T1.data_json FROM farm_notifications T1 "
                "JOIN user_farm_data T2 ON T1.user_id = T2.user_id "
                "WHERE T1.task_type = 'brewery_upgrade' AND T1.is_sent = 0 AND T2.brewery_upgrade_timer_end <= ?",
                (now.isoformat(),)
            )
            brewery_tasks = await cursor_brewery.fetchall()
            
            cursor_batch = await db.execute(
                "SELECT T1.user_id, T1.task_type, T2.brewery_batch_size FROM farm_notifications T1 "
                "JOIN user_farm_data T2 ON T1.user_id = T2.user_id "
                "WHERE T1.task_type = 'batch' AND T1.is_sent = 0 AND T2.brewery_batch_timer_end <= ?",
                (now.isoformat(),)
            )
            batch_tasks = await cursor_batch.fetchall()
            
            all_tasks = field_tasks + brewery_tasks + batch_tasks
            
            return [(uid, ttype, int(data)) for uid, ttype, data in all_tasks if data is not None]

    async def mark_notification_sent(self, user_id: int, task_type: str):
        """Помечает уведомление как отправленное."""
        async with aiosqlite.connect(self.db_name, timeout=20) as db:
            await db.execute(
                "UPDATE farm_notifications SET is_sent = 1 WHERE user_id = ? AND task_type = ?",
                (user_id, task_type)
            )
            await db.commit()

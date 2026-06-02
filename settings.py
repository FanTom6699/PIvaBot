# settings.py
import logging
from database import Database

# Названия настроек на русском языке для админ-панели
SETTINGS_NAMES = {
    # Общие
    "beer_cooldown": "Кулдаун /beer (сек)",
    "jackpot_chance": "Шанс Джекпота (1 к X)",
    "roulette_cooldown": "Кулдаун Рулетки (сек)",
    "roulette_min_bet": "Мин. ставка Рулетки",
    "roulette_max_bet": "Макс. ставка Рулетки",
    "ladder_min_bet": "Мин. ставка Лесенки",
    "ladder_max_bet": "Макс. ставка Лесенки",
}

class SettingsManager:
    def __init__(self):
        # --- Значения по умолчанию ---
        
        # Пиво и Казино
        self.beer_cooldown = 7200
        self.jackpot_chance = 100
        self.roulette_cooldown = 300
        self.roulette_min_bet = 10
        self.roulette_max_bet = 1000
        self.ladder_min_bet = 10
        self.ladder_max_bet = 500

    async def load_settings(self, db: Database):
        """Загружает все настройки из БД, обновляя дефолтные."""
        settings = await db.get_all_settings()
        for key, value in settings.items():
            if hasattr(self, key):
                setattr(self, key, value)
        logging.info("Настройки успешно загружены.")

    async def reload_setting(self, db: Database, key: str):
        """Перезагружает конкретную настройку."""
        val = await db.get_setting(key)
        if val is not None and hasattr(self, key):
            setattr(self, key, val)

    async def get_all_settings_dict(self):
        """Возвращает словарь всех настроек для генерации кнопок."""
        # Фильтруем только то, что есть в SETTINGS_NAMES (скрываем лишнее)
        return {k: v for k, v in self.__dict__.items() if k in SETTINGS_NAMES}

    # --- МЕТОДЫ ФОРМАТИРОВАНИЯ ТЕКСТА (Для Админки) ---

    def _format_setting_line(self, key: str) -> str:
        name = SETTINGS_NAMES.get(key, key)
        value = getattr(self, key, "???")
        return f"• {name}: <b>{value}</b>\n"

    def get_common_settings_text(self) -> str:
        """Возвращает текст общих настроек (Пиво, Рулетка, Лесенка)."""
        text = ""
        keys = [
            "beer_cooldown", "jackpot_chance", 
            "roulette_cooldown", "roulette_min_bet", "roulette_max_bet",
            "ladder_min_bet", "ladder_max_bet"
        ]
        for key in keys:
            text += self._format_setting_line(key)
        return text

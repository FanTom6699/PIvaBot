## main.py
import asyncio
import logging
import os
from datetime import datetime

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from handlers import main_router

from database import Database
from settings import SettingsManager

# ─────────────────────────────────────────────
# Загрузка .env
# ─────────────────────────────────────────────
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_NAME = os.getenv("DB_NAME", "bot_database.db")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не найден. Проверь файл .env")


# ─────────────────────────────────────────────
# Фоновая задача фермы
# ─────────────────────────────────────────────
async def farm_background_updater(bot: Bot, db: Database):
    logging.info("Фоновая задача (Farm Updater) запущена...")

    while True:
        await asyncio.sleep(60)

        try:
            now = datetime.now()
            pending_tasks = await db.get_pending_notifications(now)

            if not pending_tasks:
                continue

            logging.info(f"[Farm Updater] Найдено {len(pending_tasks)} задач")

            for user_id, task_type, data in pending_tasks:
                text = None

                if task_type == "batch":
                    text = f"🍻 Твоя варка (x{data}) готова! Забери награду!"
                elif task_type == "field_upgrade":
                    text = "🌾 Улучшение Поля завершено!"
                elif task_type == "brewery_upgrade":
                    text = "🏭 Улучшение Пивоварни завершено!"

                if task_type == "field_upgrade":
                    await db.finish_upgrade(user_id, "field")
                elif task_type == "brewery_upgrade":
                    await db.finish_upgrade(user_id, "brewery")

                if text:
                    try:
                        await bot.send_message(user_id, text)
                        await db.mark_notification_sent(user_id, task_type)
                        logging.info(
                            f"[Farm Updater] Отправлено {task_type} пользователю {user_id}"
                        )
                    except Exception as e:
                        logging.warning(
                            f"[Farm Updater] Не удалось отправить {task_type} пользователю {user_id}: {e}"
                        )
                        await db.mark_notification_sent(user_id, task_type)

        except Exception as e:
            logging.error(
                f"[Farm Updater] Критическая ошибка: {e}",
                exc_info=True
            )
            await asyncio.sleep(300)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )

    logging.info("Запуск Piva Bot...")

    # База и настройки
    db = Database(db_name=DB_NAME)
    settings_manager = SettingsManager()

    await db.initialize()
    await settings_manager.load_settings(db)

    # Бот
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher()
    dp["db"] = db
    dp["settings"] = settings_manager

    # Роутеры
    dp.include_router(main_router)

    # Фоновые задачи
    asyncio.create_task(farm_background_updater(bot, db))

    logging.info("🚀 Бот запущен (polling)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

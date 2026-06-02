# handlers/common.py
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from database import Database

common_router = Router()

# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ РЕГИСТРАЦИИ (ТВОЙ ТЕКСТ) ---
async def check_user_registered(message_or_callback: Message | CallbackQuery, bot: Bot, db: Database) -> bool:
    user = message_or_callback.from_user
    if await db.user_exists(user.id):
        return True
    
    me = await bot.get_me()
    start_link = f"https://t.me/{me.username}?start=register"
    
    # Твои крутые изменения:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➡️ Зайти в бар (Регистрация)", url=start_link)]])
    text = (
        "<b>Постой, незнакомец!</b> 🍻\n\n"
        "Я тебя здесь раньше не видел. Нужно сперва заглянуть ко мне в личку, чтобы я тебя 'записал' в наш клуб.\n\n"
        "Нажми кнопку ⬇️, чтобы зайти."
    )
    
    if isinstance(message_or_callback, Message):
        await message_or_callback.reply(text, reply_markup=keyboard, parse_mode='HTML')
    else:
        # Для inline-кнопок (рулетка, лесенка и т.д.)
        await message_or_callback.answer("Сначала нужно зарегистрироваться!", show_alert=True)
        await bot.send_message(message_or_callback.message.chat.id, text, reply_markup=keyboard, parse_mode='HTML')
    return False

# --- ОБРАБОТЧИКИ СОБЫТИЙ ЧАТА (без изменений) ---
@common_router.my_chat_member()
async def handle_bot_membership(event: ChatMemberUpdated, bot: Bot, db: Database):
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    if old_status in ("left", "kicked") and new_status in ("member", "administrator"):
        await db.add_chat(event.chat.id, event.chat.title)
    elif old_status in ("member", "administrator") and new_status in ("left", "kicked"):
        await db.remove_chat(event.chat.id)

# --- КОМАНДЫ ПОЛЬЗОВАТЕЛЕЙ (ТВОЙ ТЕКСТ) ---
@common_router.message(CommandStart())
async def cmd_start(message: Message, db: Database):
    user = message.from_user
    if not await db.user_exists(user.id):
        await db.add_user(user.id, user.first_name, user.last_name, user.username)
        
        # Твой новый приветственный текст:
        welcome_text = (
            f"Рад знакомству, <b>{user.full_name}</b>! 🤝\n\n"
            f"Добро пожаловать в 'Пивную'. Твоя кружка пока пуста (рейтинг: 0 🍺), но это легко исправить!\n\n"
            f"<b>Вот твоя карта бара:</b>\n"
            f"• <code>/beer</code> - Испытать удачу (раз в 2 часа).\n"
            f"• <code>/top</code> - Показать таблицу лидеров.\n"
            f"• <code>/jackpot</code> - Проверить текущий джекпот.\n"
            f"• <code>/roulette &lt;ставка&gt; &lt;игроки&gt;</code> - Запустить 'Пивную рулетку'.\n"
            f"• <code>/ladder &lt;ставка&gt;</code> - Начать игру в 'Пивную лесенку'.\n"
            f"• <code>/help</code> - Показать эту справку."
        )
        await message.answer(welcome_text, parse_mode='HTML')
    else:
        rating = await db.get_user_beer_rating(user.id)
        await message.answer(f"С возвращением, {user.full_name}! 🍻\nТвой текущий рейтинг: {rating} 🍺.")

@common_router.message(Command("help"))
async def cmd_help(message: Message):
    # Твое новое "Меню Бара":
    help_text = (
        "<b>🍻 Меню Бара (Помощь) 🍻</b>\n\n"
        "Запутался? Не беда, вот наша 'карта'.\n\n"
        "--- --- ---\n"
        "<b>Основное:</b>\n"
        "• <code>/start</code> - Зарегистрироваться или проверить свой профиль.\n"
        "• <code>/beer</code> - Испытать удачу (раз в 2 часа).\n"
        "• <code>/top</code> - Показать таблицу лидеров.\n"
        "• <code>/jackpot</code> - Проверить текущий джекпот.\n\n"
        "--- --- ---\n"
        "<b>Мини-игры:</b>\n"
        # Важно: &lt; и &gt; нужны, чтобы /set и /ladder не сломали HTML-разметку
        "• <code>/roulette &lt;ставка&gt; &lt;игроки&gt;</code> - Запустить 'Пивную рулетку' в группе.\n"
        "• <code>/ladder &lt;ставка&gt;</code> - Начать игру в 'Пивную лесенку'.\n\n"
        "--- --- ---\n"
        "<b>Прочее:</b>\n"
        "• <code>/id</code> - Узнать свой User ID и ID текущего чата."
    )
    await message.answer(help_text, parse_mode='HTML')

@common_router.message(Command("id"))
async def cmd_id(message: Message):
    await message.reply(
        f"ℹ️ **Информация:**\n\n"
        f"👤 Ваш User ID: <code>{message.from_user.id}</code>\n"
        f"💬 ID этого чата: <code>{message.chat.id}</code>",
        parse_mode='HTML'
    )

@common_router.message(Command("jackpot"))
async def cmd_jackpot(message: Message, db: Database):
    current_jackpot = await db.get_jackpot()
    await message.answer(
        f"💰 <b>Текущий Джекпот</b> 💰\n\n"
        f"В банке сейчас накоплено: <b>{current_jackpot} 🍺</b>\n\n"
        f"<i>Каждый проигрыш в <code>/beer</code> пополняет банк, и каждый, кто нажимает <code>/beer</code>, может его сорвать!</i>",
        parse_mode='HTML'
    )

# handlers/game_roulette.py
import asyncio
import random
from datetime import datetime, timedelta
from contextlib import suppress
import logging
from html import escape

from aiogram import Router, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.exceptions import TelegramBadRequest

from database import Database
from settings import SettingsManager
from .common import check_user_registered
from utils import format_time_delta

# --- ИНИЦИАЛИЗАЦИЯ ---
roulette_router = Router()

# --- CALLBACKDATA ---
class RouletteCallbackData(CallbackData, prefix="roulette"):
    action: str

# --- КЛАССЫ И КОНСТАНТЫ ---
class GameState:
    def __init__(self, creator, stake, max_players, lobby_message_id):
        self.creator = creator
        self.stake = stake
        self.max_players = max_players
        self.lobby_message_id = lobby_message_id
        self.players = {creator.id: creator}
        self.task = None

ROULETTE_LOBBY_TIMEOUT_SECONDS = 60
active_games = {}
chat_cooldowns = {}
DIVIDER = "<code>--- --- ---</code>"


# --- ФУНКЦИИ ИГРЫ ---
def get_roulette_keyboard(game: GameState) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text="🍺 Присоединиться", callback_data=RouletteCallbackData(action="join").pack()),
        InlineKeyboardButton(text="🚪 Выйти", callback_data=RouletteCallbackData(action="leave").pack()),
        InlineKeyboardButton(text="❌ Отменить", callback_data=RouletteCallbackData(action="cancel").pack()),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])

async def generate_lobby_text(game: GameState) -> str:
    players_list = "\n".join(f"• {escape(p.full_name)}" for p in game.players.values())
    return (
        "🎰 <b>Пивная рулетка</b>\n\n"
        "На стойке стоит общий банк. Один останется с кружкой, остальные уйдут без ставки.\n\n"
        f"{DIVIDER}\n"
        f"Создатель: <b>{escape(game.creator.full_name)}</b>\n"
        f"Ставка: <b>{game.stake}</b> 🍺\n"
        f"Игроки: <b>{len(game.players)}/{game.max_players}</b>\n\n"
        f"{players_list}\n\n"
        f"<i>Старт через {ROULETTE_LOBBY_TIMEOUT_SECONDS} с или при полном лобби.</i>"
    )


def get_roulette_help_text(settings: SettingsManager) -> str:
    return (
        "🎰 <b>Пивная рулетка</b>\n\n"
        "Групповая игра на выбывание. Каждый ставит 🍺, победитель забирает весь банк.\n\n"
        f"{DIVIDER}\n"
        "Формат: <code>/roulette &lt;ставка&gt; &lt;игроки&gt;</code>\n"
        f"Ставка: <b>{settings.roulette_min_bet}-{settings.roulette_max_bet}</b> 🍺\n"
        "Игроки: <b>2-6</b>\n\n"
        "Пример: <code>/roulette 10 4</code>"
    )


def get_roulette_cancel_text(reason: str) -> str:
    return (
        "🎰 <b>Пивная рулетка</b>\n\n"
        f"{reason}\n\n"
        f"{DIVIDER}\n"
        "Все ставки возвращены."
    )


def get_roulette_winner_text(winner_name: str, prize: int) -> str:
    templates = [
        (
            "🏆 <b>Бар признал победителя</b>\n\n"
            "<b>{name}</b> остался последним у стойки.\n\n"
            f"{DIVIDER}\n"
            "Банк забран: <b>+{prize}</b> 🍺"
        ),
        (
            "🍺 <b>Последняя кружка его</b>\n\n"
            "<b>{name}</b> пережил все раунды и забрал банк.\n\n"
            f"{DIVIDER}\n"
            "Выигрыш: <b>+{prize}</b> 🍺"
        ),
        (
            "🎰 <b>Барабан остановился</b>\n\n"
            "<b>{name}</b> выходит победителем пивной рулетки.\n\n"
            f"{DIVIDER}\n"
            "Забрано со стола: <b>+{prize}</b> 🍺"
        ),
        (
            "👑 <b>Король стойки</b>\n\n"
            "<b>{name}</b> забирает весь банк и спокойно допивает кружку.\n\n"
            f"{DIVIDER}\n"
            "Награда: <b>+{prize}</b> 🍺"
        ),
        (
            "🔥 <b>Все ставки сгорели</b>\n\n"
            "А <b>{name}</b> вышел сухим из пены.\n\n"
            f"{DIVIDER}\n"
            "Добыча: <b>+{prize}</b> 🍺"
        ),
        (
            "🍻 <b>Стойка опустела</b>\n\n"
            "<b>{name}</b> остался один и забрал все кружки.\n\n"
            f"{DIVIDER}\n"
            "Банк: <b>+{prize}</b> 🍺"
        ),
        (
            "💰 <b>Касса звякнула</b>\n\n"
            "<b>{name}</b> уносит общий банк.\n\n"
            f"{DIVIDER}\n"
            "Получено: <b>+{prize}</b> 🍺"
        ),
        (
            "🎲 <b>Удача села рядом</b>\n\n"
            "<b>{name}</b> пережил барабан и забрал куш.\n\n"
            f"{DIVIDER}\n"
            "Куш: <b>+{prize}</b> 🍺"
        ),
        (
            "🪑 <b>Последний стул занят</b>\n\n"
            "<b>{name}</b> досидел до конца и забрал награду.\n\n"
            f"{DIVIDER}\n"
            "Награда: <b>+{prize}</b> 🍺"
        ),
        (
            "⚡ <b>Финальный глоток</b>\n\n"
            "<b>{name}</b> выдержал рулетку до последнего.\n\n"
            f"{DIVIDER}\n"
            "Приз: <b>+{prize}</b> 🍺"
        ),
    ]
    return (
        random.choice(templates).format(name=winner_name, prize=prize)
        + "\n\n<i>Пивная рулетка закрыта до следующего раунда.</i>"
    )


@roulette_router.message(Command("roulette"))
async def cmd_roulette(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    if message.chat.type == 'private':
        return await message.answer("🎰 <b>Пивная рулетка</b>\n\nЭта игра запускается только в группе.")
    args = message.text.split()

    if len(args) != 3 or not args[1].isdigit() or not args[2].isdigit():
        return await message.reply(get_roulette_help_text(settings), parse_mode='HTML')

    chat_id = message.chat.id
    if chat_id in active_games:
        return await message.reply(
            "🎰 <b>Пивная рулетка</b>\n\n"
            "В этом чате уже открыто лобби. Доиграйте текущий раунд.",
            parse_mode='HTML'
        )
    
    roulette_cooldown = settings.roulette_cooldown
    if chat_id in chat_cooldowns:
        time_since = datetime.now() - chat_cooldowns[chat_id]
        if time_since.total_seconds() < roulette_cooldown:
            remaining = timedelta(seconds=roulette_cooldown) - time_since
            return await message.reply(
                "🎰 <b>Пивная рулетка</b>\n\n"
                "Барабан остывает после прошлой игры.\n\n"
                f"{DIVIDER}\n"
                f"Новая игра через: <b>{format_time_delta(remaining)}</b>.",
                parse_mode='HTML'
            )
            
    stake, max_players = int(args[1]), int(args[2])
    
    min_bet = settings.roulette_min_bet
    max_bet = settings.roulette_max_bet
    
    if not (min_bet <= stake <= max_bet):
        return await message.reply(f"🎰 <b>Пивная рулетка</b>\n\nСтавка должна быть от <b>{min_bet}</b> до <b>{max_bet}</b> 🍺.", parse_mode='HTML')
    if not (2 <= max_players <= 6):
        return await message.reply("🎰 <b>Пивная рулетка</b>\n\nИгроков должно быть от <b>2</b> до <b>6</b>.", parse_mode='HTML')
    
    creator = message.from_user
    if not await check_user_registered(message, bot, db): return
    creator_balance = await db.get_user_beer_rating(creator.id)
    if creator_balance < stake:
        return await message.reply(
            "🎰 <b>Пивная рулетка</b>\n\n"
            f"Для входа нужно <b>{stake}</b> 🍺, у тебя <b>{creator_balance}</b> 🍺.",
            parse_mode='HTML'
        )
    
    await db.change_rating(creator.id, -stake)
    lobby_message = await message.answer("🎰 Крупье ставит кружки на стойку...")
    game = GameState(creator, stake, max_players, lobby_message.message_id)
    active_games[chat_id] = game
    with suppress(TelegramBadRequest): await bot.pin_chat_message(chat_id=chat_id, message_id=lobby_message.message_id, disable_notification=True)
    await lobby_message.edit_text(await generate_lobby_text(game), reply_markup=get_roulette_keyboard(game), parse_mode='HTML')
    game.task = asyncio.create_task(schedule_game_start(chat_id, bot, db))

@roulette_router.callback_query(RouletteCallbackData.filter())
async def on_roulette_button_click(callback: CallbackQuery, callback_data: RouletteCallbackData, bot: Bot, db: Database):
    chat_id = callback.message.chat.id
    user = callback.from_user
    if chat_id not in active_games: return await callback.answer("Эта игра уже неактивна.", show_alert=True)
    
    game = active_games[chat_id]
    action = callback_data.action
    
    if action == "join":
        if user.id in game.players: return await callback.answer("Вы уже в игре!", show_alert=True)
        if len(game.players) >= game.max_players: return await callback.answer("Лобби заполнено.", show_alert=True)
        if not await check_user_registered(callback, bot, db): return
        balance = await db.get_user_beer_rating(user.id)
        if balance < game.stake: return await callback.answer(f"Недостаточно пива! Нужно {game.stake} 🍺, у вас {balance} 🍺.", show_alert=True)
        await db.change_rating(user.id, -game.stake)
        game.players[user.id] = user
        await callback.answer("Ты занял место у стойки.")
        if len(game.players) == game.max_players:
            if game.task: game.task.cancel()
            await start_roulette_game(chat_id, bot, db)
        else:
            await callback.message.edit_text(await generate_lobby_text(game), reply_markup=get_roulette_keyboard(game), parse_mode='HTML')
            
    elif action == "leave":
        if user.id not in game.players: return await callback.answer("Вы не в этой игре.", show_alert=True)
        if user.id == game.creator.id: return await callback.answer("Создатель не может покинуть игру. Только отменить.", show_alert=True)
        del game.players[user.id]
        await db.change_rating(user.id, game.stake)
        await callback.answer("Ты вышел из лобби. Ставка возвращена.", show_alert=True)
        await callback.message.edit_text(await generate_lobby_text(game), reply_markup=get_roulette_keyboard(game), parse_mode='HTML')
        
    elif action == "cancel":
        if user.id != game.creator.id: return await callback.answer("Только создатель может отменить игру.", show_alert=True)
        if game.task: game.task.cancel()
        for player_id in game.players: await db.change_rating(player_id, game.stake)
        del active_games[chat_id]
        with suppress(TelegramBadRequest): await bot.unpin_chat_message(chat_id=chat_id, message_id=game.lobby_message_id)
        await callback.message.edit_text(
            get_roulette_cancel_text("Создатель закрыл лобби до старта."),
            parse_mode='HTML'
        )
        await callback.answer()

async def schedule_game_start(chat_id: int, bot: Bot, db: Database):
    try:
        await asyncio.sleep(ROULETTE_LOBBY_TIMEOUT_SECONDS)
        if chat_id not in active_games: return
        game = active_games[chat_id]
        if len(game.players) >= 2:
            await start_roulette_game(chat_id, bot, db)
        else:
            await db.change_rating(game.creator.id, game.stake)
            await bot.edit_message_text(
                text=get_roulette_cancel_text("Недостаточно игроков. Барабан остался на полке."),
                chat_id=chat_id,
                message_id=game.lobby_message_id,
                reply_markup=None,
                parse_mode='HTML'
            )
            with suppress(TelegramBadRequest):
                await bot.unpin_chat_message(chat_id=chat_id, message_id=game.lobby_message_id)
            del active_games[chat_id]
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error(f"Ошибка в schedule_game_start: {e}")
        if chat_id in active_games:
            del active_games[chat_id]

async def start_roulette_game(chat_id: int, bot: Bot, db: Database):
    if chat_id not in active_games: return
    game = active_games[chat_id]
    with suppress(TelegramBadRequest): await bot.unpin_chat_message(chat_id=chat_id, message_id=game.lobby_message_id)
    await bot.edit_message_text(
        text=(
            "🎰 <b>Пивная рулетка</b>\n\n"
            "Все места заняты. Кружки на кону, барабан пошел.\n\n"
            f"{DIVIDER}\n"
            f"Ставка каждого: <b>{game.stake}</b> 🍺\n"
            f"Банк: <b>{game.stake * len(game.players)}</b> 🍺"
        ),
        chat_id=chat_id,
        message_id=game.lobby_message_id,
        reply_markup=None,
        parse_mode='HTML'
    )
    await asyncio.sleep(3)
    players_in_game = list(game.players.values())
    round_num = 1
    while len(players_in_game) > 1:
        await bot.send_message(
            chat_id,
            f"🎰 <b>Раунд {round_num}</b>\n\nБарабан крутится. За стойкой становится тише.",
            parse_mode='HTML'
        )
        await asyncio.sleep(5)
        loser = random.choice(players_in_game)
        players_in_game.remove(loser)
        remaining_players_text = "\n".join(f"• {escape(p.full_name)}" for p in players_in_game)
        await bot.send_message(
            chat_id,
            text=(
                "💥 <b>Минус кружка</b>\n\n"
                f"Выбывает: <b>{escape(loser.full_name)}</b>\n\n"
                f"{DIVIDER}\n"
                f"<b>Остались у стойки:</b>\n{remaining_players_text}"
            ),
            parse_mode='HTML'
        )
        round_num += 1
        await asyncio.sleep(7)
    winner = players_in_game[0]
    prize = game.stake * len(game.players)
    await db.change_rating(winner.id, prize)
    winner_text = get_roulette_winner_text(escape(winner.full_name), prize)
    winner_message = await bot.send_message(chat_id, text=winner_text, parse_mode='HTML')
    with suppress(TelegramBadRequest):
        await bot.pin_chat_message(chat_id=chat_id, message_id=winner_message.message_id, disable_notification=True)
        asyncio.create_task(unpin_after_delay(chat_id, winner_message.message_id, bot, 120))
    del active_games[chat_id]
    chat_cooldowns[chat_id] = datetime.now()

async def unpin_after_delay(chat_id: int, message_id: int, bot: Bot, delay: int):
    await asyncio.sleep(delay)
    with suppress(TelegramBadRequest):
        await bot.unpin_chat_message(chat_id=chat_id, message_id=message_id)

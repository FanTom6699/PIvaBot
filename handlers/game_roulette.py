# handlers/game_roulette.py
import asyncio
import random
from datetime import datetime, timedelta
from contextlib import suppress
import logging

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


# --- ФУНКЦИИ ИГРЫ ---
def get_roulette_keyboard(game: GameState, user_id: int) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text="🍺 Присоединиться", callback_data=RouletteCallbackData(action="join").pack())]
    if user_id in game.players:
        if user_id == game.creator.id:
            buttons.append(InlineKeyboardButton(text="❌ Отменить игру", callback_data=RouletteCallbackData(action="cancel").pack()))
        else:
            buttons.append(InlineKeyboardButton(text="🚪 Выйти", callback_data=RouletteCallbackData(action="leave").pack()))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])

async def generate_lobby_text(game: GameState) -> str:
    players_list = "\n".join(f"• {p.full_name}" for p in game.players.values())
    return (
        f"🍻 <b>Пивная рулетка началась!</b> 🍻\n\n"
        f"Создал игру: <b>{game.creator.full_name}</b>\n"
        f"Ставка для входа: <b>{game.stake} 🍺</b>\n"
        f"Игроки: ({len(game.players)}/{game.max_players})\n{players_list}\n\n"
        f"<i>Игра начнется через {ROULETTE_LOBBY_TIMEOUT_SECONDS} секунд или когда наберется {game.max_players} игроков.</i>"
    )

@roulette_router.message(Command("roulette"))
async def cmd_roulette(message: Message, bot: Bot, db: Database, settings: SettingsManager):
    if message.chat.type == 'private': return await message.answer("Эта команда работает только в групповых чатах.")
    args = message.text.split()
    
    # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
    if len(args) != 3 or not args[1].isdigit() or not args[2].isdigit():
        return await message.reply(
            "ℹ️ <b>Как запустить 'Пивную рулетку':</b>\n"
            # Было: /roulette <ставка> <игроки>
            "Используйте команду: <code>/roulette &lt;ставка&gt; &lt;игроки&gt;</code>\n\n"
            f"• <code>&lt;ставка&gt;</code>: от {settings.roulette_min_bet} до {settings.roulette_max_bet} 🍺\n"
            "• <code>&lt;игроки&gt;</code>: от 2 до 6 человек\n\n"
            "Пример: <code>/roulette 10 4</code>", parse_mode='HTML'
        )
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

    chat_id = message.chat.id
    if chat_id in active_games: return await message.reply("В этом чате уже идет игра.")
    
    roulette_cooldown = settings.roulette_cooldown
    if chat_id in chat_cooldowns:
        time_since = datetime.now() - chat_cooldowns[chat_id]
        if time_since.total_seconds() < roulette_cooldown:
            remaining = timedelta(seconds=roulette_cooldown) - time_since
            return await message.reply(f"Создавать новую игру можно будет через: {format_time_delta(remaining)}.")
            
    stake, max_players = int(args[1]), int(args[2])
    
    min_bet = settings.roulette_min_bet
    max_bet = settings.roulette_max_bet
    
    if not (min_bet <= stake <= max_bet):
        return await message.reply(f"Ставка должна быть от {min_bet} до {max_bet} 🍺.")
    if not (2 <= max_players <= 6): return await message.reply("Количество игроков должно быть от 2 до 6.")
    
    creator = message.from_user
    if not await check_user_registered(message, bot, db): return
    creator_balance = await db.get_user_beer_rating(creator.id)
    if creator_balance < stake: return await message.reply(f"У вас недостаточно пива. Нужно {stake} 🍺, у вас {creator_balance} 🍺.")
    
    await db.change_rating(creator.id, -stake)
    lobby_message = await message.answer("Создание лобби...")
    game = GameState(creator, stake, max_players, lobby_message.message_id)
    active_games[chat_id] = game
    with suppress(TelegramBadRequest): await bot.pin_chat_message(chat_id=chat_id, message_id=lobby_message.message_id, disable_notification=True)
    await lobby_message.edit_text(await generate_lobby_text(game), reply_markup=get_roulette_keyboard(game, creator.id), parse_mode='HTML')
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
        await callback.answer("Вы присоединились к игре!")
        if len(game.players) == game.max_players:
            if game.task: game.task.cancel()
            await start_roulette_game(chat_id, bot, db)
        else:
            await callback.message.edit_text(await generate_lobby_text(game), reply_markup=get_roulette_keyboard(game, user.id), parse_mode='HTML')
            
    elif action == "leave":
        if user.id not in game.players: return await callback.answer("Вы не в этой игре.", show_alert=True)
        if user.id == game.creator.id: return await callback.answer("Создатель не может покинуть игру. Только отменить.", show_alert=True)
        del game.players[user.id]
        await db.change_rating(user.id, game.stake)
        await callback.answer("Вы покинули игру, ваша ставка возвращена.", show_alert=True)
        await callback.message.edit_text(await generate_lobby_text(game), reply_markup=get_roulette_keyboard(game, user.id), parse_mode='HTML')
        
    elif action == "cancel":
        if user.id != game.creator.id: return await callback.answer("Только создатель может отменить игру.", show_alert=True)
        if game.task: game.task.cancel()
        for player_id in game.players: await db.change_rating(player_id, game.stake)
        del active_games[chat_id]
        with suppress(TelegramBadRequest): await bot.unpin_chat_message(chat_id=chat_id, message_id=game.lobby_message_id)
        await callback.message.edit_text("Игра отменена создателем. Все ставки возвращены.")
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
            await bot.edit_message_text(text="Недостаточно игроков. Игра отменена.", chat_id=chat_id, message_id=game.lobby_message_id, reply_markup=None)
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
    await bot.edit_message_text(text=f"Все в сборе! Ставки ({game.stake} 🍺 с каждого). Крутим барабан... 🔫", chat_id=chat_id, message_id=game.lobby_message_id, reply_markup=None)
    await asyncio.sleep(3)
    players_in_game = list(game.players.values())
    round_num = 1
    while len(players_in_game) > 1:
        await bot.send_message(chat_id, f"🍻 <b>Раунд {round_num}</b>. Крутим барабан... 🔫", parse_mode='HTML')
        await asyncio.sleep(5)
        loser = random.choice(players_in_game)
        players_in_game.remove(loser)
        remaining_players_text = "\n".join(f"• {p.full_name}" for p in players_in_game)
        await bot.send_message(
            chat_id,
            text=f"Выбывает... <b>{loser.full_name}</b>! 😖\n\n"
                 f"<i>Остались в игре:</i>\n{remaining_players_text}",
            parse_mode='HTML'
        )
        round_num += 1
        await asyncio.sleep(7)
    winner = players_in_game[0]
    prize = game.stake * len(game.players)
    await db.change_rating(winner.id, prize)
    winner_text = (
        f"🏆 <b>ПОБЕДИТЕЛЬ!</b> 🏆\n\n"
        f"Поздравляем, <b>{winner.full_name}</b>! Он забирает весь банк: <b>{prize} 🍺</b>!\n\n"
        f"<i>Игра окончена.</i>"
    )
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

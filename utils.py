from datetime import timedelta
from html import escape


active_lobby_timers = {}
active_games = {}
GAME_ACTIVE_KEY = "game_active"


def format_time_delta(time_delta: timedelta) -> str:
    """Format timedelta as '1 ч 02 м 05 с', '2 м 05 с', or '5 с'."""
    total_seconds = max(0, int(time_delta.total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if hours:
        parts.append(f"{hours} ч")
    if minutes:
        parts.append(f"{minutes} м")
    if seconds or not parts:
        if hours or minutes:
            parts.append(f"{seconds:02d} с")
        else:
            parts.append(f"{seconds} с")

    return " ".join(parts)


def format_time_left(total_seconds: int) -> str:
    if total_seconds < 0:
        total_seconds = 0

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def mention_user(user_id: int, name: str | None) -> str:
    safe_name = escape(name or "Игрок")
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'


def mention_user_from_parts(user_id: int, first_name: str | None, last_name: str | None = None) -> str:
    name = first_name or "Игрок"
    if last_name:
        name += f" {last_name}"
    return mention_user(user_id, name)

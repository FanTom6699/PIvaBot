from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class AssistantConfig:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_phone: str | None
    session_name: str
    target_bot: str
    database_path: Path
    recipes_path: Path
    rules_path: Path
    openai_api_key: str | None
    openai_model: str
    dry_run: bool
    loop_interval_seconds: int
    max_history_messages: int
    milking_enabled: bool

    @classmethod
    def from_env(cls) -> "AssistantConfig":
        load_dotenv()

        api_id = os.getenv("TG_API_ID")
        api_hash = os.getenv("TG_API_HASH")
        if not api_id or not api_hash:
            raise RuntimeError("Нужно указать TG_API_ID и TG_API_HASH в .env")

        return cls(
            telegram_api_id=int(api_id),
            telegram_api_hash=api_hash,
            telegram_phone=os.getenv("TG_PHONE"),
            session_name=os.getenv("TG_SESSION", "mafiozi_assistant"),
            target_bot=os.getenv("TARGET_BOT", "@moolokobot"),
            database_path=Path(os.getenv("ASSISTANT_DB", PROJECT_ROOT / "assistant.db")),
            recipes_path=Path(os.getenv("RECIPES_PATH", PROJECT_ROOT / "recipes.json")),
            rules_path=Path(os.getenv("RULES_PATH", PROJECT_ROOT / "rules.json")),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            dry_run=_bool_env("DRY_RUN", True),
            loop_interval_seconds=int(os.getenv("LOOP_INTERVAL_SECONDS", "5")),
            max_history_messages=int(os.getenv("MAX_HISTORY_MESSAGES", "20")),
            milking_enabled=_bool_env("MILKING_ENABLED", True),
        )

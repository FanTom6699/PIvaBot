from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .database import Database
from .parser import ParsedMessage


class GameMemory:
    def __init__(self, db: Database):
        self.db = db

    async def update_from_message(self, parsed: ParsedMessage) -> None:
        for name, amount in parsed.resources.items():
            await self.db.upsert_resource(name, amount)

        for index, task in enumerate(parsed.tasks):
            await self.db.upsert_json("tasks", f"task:{index}:{task.get('text', '')[:80]}", task)

        for index, animal in enumerate(parsed.animals):
            await self.db.upsert_json("animals", f"animal:{index}:{animal.get('text', '')[:80]}", animal)

        for index, timer in enumerate(parsed.timers):
            key = f"timer:{timer['label'][:80]}"
            await self.db.upsert_timer(key, timer["label"], timer["ready_at"], timer)

        await self.db.add_snapshot(parsed.message_id, asdict(parsed))

    async def build_state(self, parsed: ParsedMessage | None = None) -> dict[str, Any]:
        state = {
            "resources": await self.db.list_resources(),
            "tasks": await self.db.list_json("tasks"),
            "animals": await self.db.list_json("animals"),
            "next_timer": await self.db.next_timer(),
            "recent_actions": await self.db.recent_actions(),
        }
        if parsed:
            state["current_message"] = {
                "id": parsed.message_id,
                "text": parsed.text,
                "buttons": [asdict(button) for button in parsed.buttons],
                "resources_seen": parsed.resources,
                "timers_seen": parsed.timers,
                "account": parsed.account,
            }
        return state


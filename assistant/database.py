from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.init_schema()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    @property
    def db(self) -> aiosqlite.Connection:
        if not self.conn:
            raise RuntimeError("Database is not connected")
        return self.conn

    async def init_schema(self) -> None:
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS resources (
                name TEXT PRIMARY KEY,
                amount INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS animals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS timers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                label TEXT NOT NULL,
                ready_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                payload TEXT NOT NULL,
                result TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        await self.db.commit()

    async def upsert_resource(self, name: str, amount: int) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        await self.db.execute(
            """
            INSERT INTO resources (name, amount, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET amount = excluded.amount, updated_at = excluded.updated_at
            """,
            (name, amount, now),
        )
        await self.db.commit()

    async def list_resources(self) -> dict[str, int]:
        cursor = await self.db.execute("SELECT name, amount FROM resources ORDER BY name")
        rows = await cursor.fetchall()
        return {row["name"]: row["amount"] for row in rows}

    async def upsert_json(self, table: str, key: str, payload: dict[str, Any]) -> None:
        if table not in {"tasks", "animals"}:
            raise ValueError(f"Unsupported table: {table}")
        now = datetime.now().isoformat(timespec="seconds")
        await self.db.execute(
            f"""
            INSERT INTO {table} (key, payload, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
            """,
            (key, json.dumps(payload, ensure_ascii=False), now),
        )
        await self.db.commit()

    async def list_json(self, table: str) -> list[dict[str, Any]]:
        if table not in {"tasks", "animals"}:
            raise ValueError(f"Unsupported table: {table}")
        cursor = await self.db.execute(f"SELECT payload FROM {table} ORDER BY updated_at DESC")
        rows = await cursor.fetchall()
        return [json.loads(row["payload"]) for row in rows]

    async def upsert_timer(self, key: str, label: str, ready_at: str, payload: dict[str, Any]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        await self.db.execute(
            """
            INSERT INTO timers (key, label, ready_at, payload, completed, updated_at)
            VALUES (?, ?, ?, ?, 0, ?)
            ON CONFLICT(key) DO UPDATE SET
                label = excluded.label,
                ready_at = excluded.ready_at,
                payload = excluded.payload,
                completed = 0,
                updated_at = excluded.updated_at
            """,
            (key, label, ready_at, json.dumps(payload, ensure_ascii=False), now),
        )
        await self.db.commit()

    async def due_timers(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now()
        cursor = await self.db.execute(
            """
            SELECT key, label, ready_at, payload
            FROM timers
            WHERE completed = 0 AND ready_at <= ?
            ORDER BY ready_at ASC
            """,
            (now.isoformat(timespec="seconds"),),
        )
        rows = await cursor.fetchall()
        return [
            {
                "key": row["key"],
                "label": row["label"],
                "ready_at": row["ready_at"],
                "payload": json.loads(row["payload"]),
            }
            for row in rows
        ]

    async def next_timer(self) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            """
            SELECT key, label, ready_at, payload
            FROM timers
            WHERE completed = 0
            ORDER BY ready_at ASC
            LIMIT 1
            """
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "key": row["key"],
            "label": row["label"],
            "ready_at": row["ready_at"],
            "payload": json.loads(row["payload"]),
        }

    async def complete_timer(self, key: str) -> None:
        await self.db.execute("UPDATE timers SET completed = 1 WHERE key = ?", (key,))
        await self.db.commit()

    async def get_timer(self, key: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT key, label, ready_at, payload FROM timers WHERE key = ? AND completed = 0",
            (key,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "key": row["key"],
            "label": row["label"],
            "ready_at": row["ready_at"],
            "payload": json.loads(row["payload"]),
        }

    async def add_action(self, action: str, payload: dict[str, Any], result: str | None = None) -> None:
        await self.db.execute(
            "INSERT INTO actions (action, payload, result, created_at) VALUES (?, ?, ?, ?)",
            (
                action,
                json.dumps(payload, ensure_ascii=False),
                result,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        await self.db.commit()

    async def recent_actions(self, limit: int = 20) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT action, payload, result, created_at FROM actions ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "action": row["action"],
                "payload": json.loads(row["payload"]),
                "result": row["result"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def add_snapshot(self, message_id: int | None, payload: dict[str, Any]) -> None:
        await self.db.execute(
            "INSERT INTO snapshots (message_id, payload, created_at) VALUES (?, ?, ?)",
            (message_id, json.dumps(payload, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
        )
        await self.db.commit()

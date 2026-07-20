"""SQLite persistence for monitors and per-performance availability state."""
from __future__ import annotations

import time
from dataclasses import dataclass

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    url        TEXT    NOT NULL,
    theatre    TEXT    NOT NULL,
    title      TEXT    NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(chat_id, url)
);

CREATE TABLE IF NOT EXISTS perf_state (
    monitor_id INTEGER NOT NULL,
    perf_key   TEXT    NOT NULL,
    available  INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (monitor_id, perf_key),
    FOREIGN KEY (monitor_id) REFERENCES monitors(id) ON DELETE CASCADE
);
"""


@dataclass(frozen=True)
class Monitor:
    id: int
    chat_id: int
    url: str
    theatre: str
    title: str


class Storage:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Storage.connect() was not called")
        return self._db

    # ----- monitors -------------------------------------------------------
    async def add_monitor(
        self, chat_id: int, url: str, theatre: str, title: str
    ) -> int | None:
        """Insert a monitor. Returns its id, or None if it already existed."""
        try:
            cur = await self.db.execute(
                "INSERT INTO monitors (chat_id, url, theatre, title, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (chat_id, url, theatre, title, int(time.time())),
            )
            await self.db.commit()
            return cur.lastrowid
        except aiosqlite.IntegrityError:
            return None

    async def list_monitors(self, chat_id: int) -> list[Monitor]:
        cur = await self.db.execute(
            "SELECT id, chat_id, url, theatre, title FROM monitors "
            "WHERE chat_id = ? ORDER BY id",
            (chat_id,),
        )
        rows = await cur.fetchall()
        return [Monitor(*row) for row in rows]

    async def all_monitors(self) -> list[Monitor]:
        cur = await self.db.execute(
            "SELECT id, chat_id, url, theatre, title FROM monitors ORDER BY id"
        )
        rows = await cur.fetchall()
        return [Monitor(*row) for row in rows]

    async def get_monitor(self, chat_id: int, monitor_id: int) -> Monitor | None:
        cur = await self.db.execute(
            "SELECT id, chat_id, url, theatre, title FROM monitors "
            "WHERE chat_id = ? AND id = ?",
            (chat_id, monitor_id),
        )
        row = await cur.fetchone()
        return Monitor(*row) if row else None

    async def remove_monitor(self, chat_id: int, monitor_id: int) -> bool:
        cur = await self.db.execute(
            "DELETE FROM monitors WHERE chat_id = ? AND id = ?",
            (chat_id, monitor_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    # ----- availability state --------------------------------------------
    async def get_state(self, monitor_id: int) -> dict[str, bool]:
        cur = await self.db.execute(
            "SELECT perf_key, available FROM perf_state WHERE monitor_id = ?",
            (monitor_id,),
        )
        return {key: bool(av) for key, av in await cur.fetchall()}

    async def set_state(self, monitor_id: int, perf_key: str, available: bool) -> None:
        await self.db.execute(
            "INSERT INTO perf_state (monitor_id, perf_key, available, updated_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(monitor_id, perf_key) DO UPDATE SET"
            " available = excluded.available, updated_at = excluded.updated_at",
            (monitor_id, perf_key, int(available), int(time.time())),
        )
        await self.db.commit()

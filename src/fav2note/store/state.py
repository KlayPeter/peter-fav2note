"""处理状态：sqlite 记账，支持断点续跑与失败重试。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    key        TEXT PRIMARY KEY,
    platform   TEXT NOT NULL,
    title      TEXT,
    status     TEXT NOT NULL DEFAULT 'pending',
    note_path  TEXT,
    error      TEXT,
    seconds    REAL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_status ON items(status);
"""


class StateStore:
    """所有状态变更都走这里，避免散落的 json 读写。"""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def status(self, key: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute("SELECT status FROM items WHERE key = ?", (key,)).fetchone()
        return row["status"] if row else None

    def set(
        self,
        key: str,
        platform: str,
        title: str,
        status: str,
        *,
        note_path: str = "",
        error: str = "",
        seconds: float = 0.0,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO items (key, platform, title, status, note_path, error, seconds, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    status = excluded.status,
                    note_path = excluded.note_path,
                    error = excluded.error,
                    seconds = excluded.seconds,
                    updated_at = excluded.updated_at
                """,
                (key, platform, title, status, note_path, error[:500], seconds,
                 datetime.now().isoformat(timespec="seconds")),
            )

    def counts(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS n FROM items GROUP BY status").fetchall()
        return {row["status"]: row["n"] for row in rows}

    def pending(self, platform: str | None = None) -> list[str]:
        sql = "SELECT key FROM items WHERE status IN ('pending', 'failed')"
        args: tuple = ()
        if platform:
            sql += " AND platform = ?"
            args = (platform,)
        with self._conn() as conn:
            return [row["key"] for row in conn.execute(sql, args)]

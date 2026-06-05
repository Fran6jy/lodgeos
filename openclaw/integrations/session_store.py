"""
Chat session state for interactive flows (e.g. correction menus).

A minimal in-memory store with TTL — enough for single-process bots. The
interface (put / get / pop) is deliberately small so it can be swapped for a
Redis-backed implementation in production without touching call sites.
"""

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


class SessionStore:
    def __init__(self, ttl_seconds: int = 600):
        self.ttl = ttl_seconds
        self._data: Dict[str, tuple[float, Any]] = {}

    def put(self, payload: Any) -> str:
        """Store a payload, return a short token to reference it."""
        token = uuid.uuid4().hex[:8]
        self._data[token] = (time.time(), payload)
        self._gc()
        return token

    def get(self, token: str) -> Optional[Any]:
        item = self._data.get(token)
        if not item:
            return None
        ts, payload = item
        if time.time() - ts > self.ttl:
            self._data.pop(token, None)
            return None
        return payload

    def pop(self, token: str) -> Optional[Any]:
        payload = self.get(token)
        self._data.pop(token, None)
        return payload

    def _gc(self) -> None:
        now = time.time()
        expired = [k for k, (ts, _) in self._data.items() if now - ts > self.ttl]
        for k in expired:
            self._data.pop(k, None)


class SqliteSessionStore:
    """SQLite-backed session store — survives process restarts.

    Drop-in for SessionStore (same put/get/pop). Payloads must be JSON-serialisable.
    """

    def __init__(self, db_path: str = "openclaw.db", ttl_seconds: int = 600):
        self.db_path = str(db_path)
        self.ttl = ttl_seconds
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sessions "
                "(token TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at REAL NOT NULL)"
            )

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def put(self, payload: Any) -> str:
        token = uuid.uuid4().hex[:8]
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sessions (token, payload, created_at) VALUES (?, ?, ?)",
                (token, json.dumps(payload), time.time()),
            )
            self._gc(conn)
            conn.commit()
        return token

    def get(self, token: str) -> Optional[Any]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload, created_at FROM sessions WHERE token = ?", (token,)
            ).fetchone()
        if not row:
            return None
        if time.time() - row["created_at"] > self.ttl:
            self.pop(token)
            return None
        return json.loads(row["payload"])

    def pop(self, token: str) -> Optional[Any]:
        payload = self.get(token)
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
        return payload

    def _gc(self, conn) -> None:
        conn.execute("DELETE FROM sessions WHERE created_at < ?", (time.time() - self.ttl,))

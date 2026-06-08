"""
SQLite storage adapter.

All records are stored in a single `records` table with a JSON `data` column
for flexibility, plus indexed columns for fast querying.

Schema supports:
- Full audit trail (created_at, updated_at never mutated — append-only)
- Multi-domain records
- Amount filtering and date range queries
"""

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS records (
    id          TEXT PRIMARY KEY,
    domain      TEXT NOT NULL,
    type        TEXT NOT NULL,
    amount      REAL,
    currency    TEXT DEFAULT 'GBP',
    description TEXT,
    timestamp   TEXT NOT NULL,
    user_id     TEXT DEFAULT 'default',
    confidence  REAL,
    data        TEXT NOT NULL,          -- full JSON record
    created_at  TEXT NOT NULL,
    updated_at  TEXT,                   -- set when a correction edits the row
    voided      INTEGER DEFAULT 0,      -- soft delete: kept for audit, excluded from totals
    space       TEXT DEFAULT 'Personal' -- Budget Space this record belongs to
);

CREATE INDEX IF NOT EXISTS idx_records_domain    ON records(domain);
CREATE INDEX IF NOT EXISTS idx_records_type      ON records(type);
CREATE INDEX IF NOT EXISTS idx_records_timestamp ON records(timestamp);
CREATE INDEX IF NOT EXISTS idx_records_user      ON records(user_id);

CREATE TABLE IF NOT EXISTS budgets (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    category    TEXT NOT NULL,
    amount      REAL NOT NULL,
    currency    TEXT DEFAULT 'GBP',
    period      TEXT NOT NULL,          -- 'weekly' | 'monthly'
    created_at  TEXT NOT NULL,
    UNIQUE(user_id, category, period)
);

CREATE TABLE IF NOT EXISTS dashboard_tokens (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL           -- epoch seconds; link dies after this
);

CREATE TABLE IF NOT EXISTS user_prefs (
    user_id      TEXT PRIMARY KEY,
    active_space TEXT DEFAULT 'Personal'
);

CREATE TABLE IF NOT EXISTS user_spaces (
    user_id  TEXT NOT NULL,
    space    TEXT NOT NULL,
    UNIQUE(user_id, space)
);
"""


class SQLiteAdapter:
    """Thread-safe SQLite adapter for OpenClaw records."""

    def __init__(self, db_path: str = "openclaw.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(DDL)
            self._migrate(conn)
        logger.info("SQLite initialised at %s", self.db_path)

    @staticmethod
    def _migrate(conn) -> None:
        """Add columns introduced after the original schema (idempotent)."""
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(records)")}
        if "updated_at" not in existing:
            conn.execute("ALTER TABLE records ADD COLUMN updated_at TEXT")
        if "voided" not in existing:
            conn.execute("ALTER TABLE records ADD COLUMN voided INTEGER DEFAULT 0")
        if "space" not in existing:
            conn.execute("ALTER TABLE records ADD COLUMN space TEXT DEFAULT 'Personal'")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Records
    # -------------------------------------------------------------------------

    def insert_record(self, record: Dict[str, Any]) -> str:
        record_id = record.get("id") or str(uuid.uuid4())
        record["id"] = record_id
        now = datetime.now().isoformat()

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO records
                    (id, domain, type, amount, currency, description,
                     timestamp, user_id, confidence, data, created_at, space)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record_id,
                    record.get("domain", "general"),
                    record.get("type", "general_note"),
                    record.get("amount"),
                    record.get("currency", "GBP"),
                    record.get("description", ""),
                    record.get("timestamp", now),
                    record.get("user_id", "default"),
                    record.get("confidence", 0.5),
                    json.dumps(record),
                    now,
                    record.get("space", "Personal"),
                ),
            )
        logger.debug("Stored record %s (domain=%s)", record_id, record.get("domain"))
        return record_id

    def query_records(
        self,
        domain: Optional[str] = None,
        record_type: Optional[str] = None,
        user_id: str = "default",
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
        include_voided: bool = False,
        space: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses = ["user_id = ?"]
        params: List[Any] = [user_id]

        if not include_voided:
            clauses.append("COALESCE(voided, 0) = 0")
        if space:
            clauses.append("COALESCE(space, 'Personal') = ?")
            params.append(space)

        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        if record_type:
            clauses.append("type = ?")
            params.append(record_type)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp <= ?")
            params.append(until)

        where = " AND ".join(clauses)
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT data FROM records WHERE {where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()

        return [json.loads(r["data"]) for r in rows]

    def sum_amount(
        self,
        domain: str,
        record_type: Optional[str] = None,
        user_id: str = "default",
        since: Optional[str] = None,
        until: Optional[str] = None,
        category: Optional[str] = None,
        space: Optional[str] = None,
    ) -> float:
        clauses = ["domain = ?", "user_id = ?", "COALESCE(voided, 0) = 0"]
        params: List[Any] = [domain, user_id]

        if space:
            clauses.append("COALESCE(space, 'Personal') = ?")
            params.append(space)
        if record_type:
            clauses.append("type = ?")
            params.append(record_type)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp <= ?")
            params.append(until)
        if category:
            # category lives inside JSON data
            clauses.append("json_extract(data, '$.entities.category') = ?")
            params.append(category)

        where = " AND ".join(clauses)
        with self._conn() as conn:
            result = conn.execute(
                f"SELECT COALESCE(SUM(amount), 0) FROM records WHERE {where}",
                params,
            ).scalar() if hasattr(conn, "scalar") else conn.execute(
                f"SELECT COALESCE(SUM(amount), 0) FROM records WHERE {where}",
                params,
            ).fetchone()[0]

        return float(result or 0)

    def get_record(self, record_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT data FROM records WHERE id = ?", (record_id,)
            ).fetchone()
        return json.loads(row["data"]) if row else None

    def search_records(
        self,
        user_id: str = "default",
        approx_amount: Optional[float] = None,
        keyword: Optional[str] = None,
        amount_tolerance: float = 0.01,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Find candidate records for a correction, most-recent first.

        Matches on an approximate amount (within tolerance) and/or a
        case-insensitive keyword in the description. Voided rows are excluded.
        """
        clauses = ["user_id = ?", "COALESCE(voided, 0) = 0"]
        params: List[Any] = [user_id]

        if approx_amount is not None:
            clauses.append("amount BETWEEN ? AND ?")
            params.extend([approx_amount - amount_tolerance, approx_amount + amount_tolerance])
        if keyword:
            clauses.append("LOWER(description) LIKE ?")
            params.append(f"%{keyword.lower()}%")

        where = " AND ".join(clauses)
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT data FROM records WHERE {where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def void_record(self, record_id: str) -> bool:
        """Soft-delete: mark the record voided. Returns True if a row changed."""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE records SET voided = 1, updated_at = ? WHERE id = ? AND COALESCE(voided, 0) = 0",
                (now, record_id),
            )
            if cur.rowcount:
                # Reflect the void inside the JSON payload too, for a self-contained audit.
                row = conn.execute("SELECT data FROM records WHERE id = ?", (record_id,)).fetchone()
                if row:
                    data = json.loads(row["data"])
                    data["voided"] = True
                    data["voided_at"] = now
                    conn.execute("UPDATE records SET data = ? WHERE id = ?", (json.dumps(data), record_id))
            return bool(cur.rowcount)

    def update_record(self, record_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Apply field updates to a record, keeping a prior-value audit snapshot.

        Allowed fields: amount, description, currency, and entities.category.
        Returns the updated record dict, or None if not found / voided.
        """
        now = datetime.now().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT data FROM records WHERE id = ? AND COALESCE(voided, 0) = 0", (record_id,)
            ).fetchone()
            if not row:
                return None
            record = json.loads(row["data"])

            # Snapshot the fields we're about to change (audit trail).
            snapshot = {"at": now, "previous": {}}
            if updates.get("amount") is not None:
                snapshot["previous"]["amount"] = record.get("amount")
                record["amount"] = float(updates["amount"])
            if updates.get("description"):
                snapshot["previous"]["description"] = record.get("description")
                record["description"] = updates["description"]
            if updates.get("currency"):
                snapshot["previous"]["currency"] = record.get("currency")
                record["currency"] = updates["currency"]
            if updates.get("category"):
                entities = record.setdefault("entities", {})
                snapshot["previous"]["category"] = entities.get("category")
                entities["category"] = updates["category"]

            record.setdefault("_history", []).append(snapshot)
            record["updated_at"] = now

            conn.execute(
                "UPDATE records SET amount = ?, currency = ?, description = ?, data = ?, updated_at = ? WHERE id = ?",
                (
                    record.get("amount"),
                    record.get("currency", "GBP"),
                    record.get("description", ""),
                    json.dumps(record),
                    now,
                    record_id,
                ),
            )
            return record

    # -------------------------------------------------------------------------
    # Budgets
    # -------------------------------------------------------------------------

    def upsert_budget(
        self,
        user_id: str,
        category: str,
        amount: float,
        period: str,
        currency: str = "GBP",
    ) -> None:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO budgets (id, user_id, category, amount, currency, period, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, category, period) DO UPDATE SET amount=excluded.amount
                """,
                (str(uuid.uuid4()), user_id, category, amount, currency, period, now),
            )

    def get_budgets(self, user_id: str, period: str = "monthly") -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM budgets WHERE user_id = ? AND period = ?",
                (user_id, period),
            ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Dashboard access tokens (per-user private links)
    # -------------------------------------------------------------------------

    def create_dashboard_token(self, user_id: str, ttl_seconds: int = 3600) -> str:
        """Mint a single-user, time-limited token granting read access to this user only."""
        import secrets
        import time
        token = secrets.token_urlsafe(24)
        now = time.time()
        with self._conn() as conn:
            # One active token per user keeps things tidy: replace any prior one.
            conn.execute("DELETE FROM dashboard_tokens WHERE user_id = ?", (user_id,))
            conn.execute(
                "INSERT INTO dashboard_tokens (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                (token, user_id, now, now + ttl_seconds),
            )
        return token

    def resolve_dashboard_token(self, token: str) -> Optional[str]:
        """Return the user_id for a valid, unexpired token, else None."""
        import time
        with self._conn() as conn:
            row = conn.execute(
                "SELECT user_id, expires_at FROM dashboard_tokens WHERE token = ?", (token,)
            ).fetchone()
        if not row or row["expires_at"] < time.time():
            return None
        return row["user_id"]

    # -------------------------------------------------------------------------
    # Budget Spaces
    # -------------------------------------------------------------------------

    DEFAULT_SPACES = ["Personal", "Business", "Property"]

    def get_active_space(self, user_id: str) -> str:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT active_space FROM user_prefs WHERE user_id = ?", (user_id,)
            ).fetchone()
        return row["active_space"] if row and row["active_space"] else "Personal"

    def set_active_space(self, user_id: str, space: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO user_prefs (user_id, active_space) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET active_space = excluded.active_space",
                (user_id, space),
            )
            # Remember the space even before it has any records.
            conn.execute(
                "INSERT OR IGNORE INTO user_spaces (user_id, space) VALUES (?, ?)",
                (user_id, space),
            )

    def list_spaces(self, user_id: str) -> List[str]:
        """Spaces this user has used or created, merged with sensible defaults."""
        with self._conn() as conn:
            used = [r["s"] for r in conn.execute(
                "SELECT DISTINCT COALESCE(space, 'Personal') AS s FROM records WHERE user_id = ?",
                (user_id,),
            ).fetchall()]
            created = [r["space"] for r in conn.execute(
                "SELECT space FROM user_spaces WHERE user_id = ?", (user_id,)
            ).fetchall()]
        spaces = self.DEFAULT_SPACES + used + created + [self.get_active_space(user_id)]
        return list(dict.fromkeys(spaces))

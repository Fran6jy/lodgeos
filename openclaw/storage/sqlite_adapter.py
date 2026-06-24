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
from typing import Any, Dict, List, Optional, Tuple

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
    space       TEXT DEFAULT 'Personal',
    category    TEXT NOT NULL,
    amount      REAL NOT NULL,
    currency    TEXT DEFAULT 'GBP',
    period      TEXT NOT NULL,          -- 'weekly' | 'monthly'
    created_at  TEXT NOT NULL,
    UNIQUE(user_id, space, category, period)
);

CREATE TABLE IF NOT EXISTS dashboard_tokens (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL           -- epoch seconds; link dies after this
);

CREATE TABLE IF NOT EXISTS user_prefs (
    user_id          TEXT PRIMARY KEY,
    active_space     TEXT DEFAULT 'Personal',
    tutorial_done    INTEGER DEFAULT 0,
    digest_enabled   INTEGER DEFAULT 0,
    briefing_enabled INTEGER DEFAULT 0,
    active_list      TEXT
);

CREATE TABLE IF NOT EXISTS user_spaces (
    user_id  TEXT NOT NULL,
    space    TEXT NOT NULL,
    UNIQUE(user_id, space)
);

CREATE TABLE IF NOT EXISTS shopping_items (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    space       TEXT DEFAULT 'Personal',
    list_name   TEXT NOT NULL,
    item        TEXT NOT NULL,
    amount      REAL,                   -- unit price (estimated until bought)
    quantity    REAL DEFAULT 1,         -- how many units
    category    TEXT,                   -- optional explicit category tag
    currency    TEXT DEFAULT 'GBP',
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shopping_list ON shopping_items(user_id, space, list_name);
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

        # Budgets gained a `space` column + a wider UNIQUE(user_id, space, category,
        # period). The old UNIQUE can't be altered in place, so rebuild the table.
        bcols = {row["name"] for row in conn.execute("PRAGMA table_info(budgets)")}
        if bcols and "space" not in bcols:
            conn.execute("ALTER TABLE budgets RENAME TO budgets_old")
            conn.execute(
                """CREATE TABLE budgets (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, space TEXT DEFAULT 'Personal',
                    category TEXT NOT NULL, amount REAL NOT NULL, currency TEXT DEFAULT 'GBP',
                    period TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(user_id, space, category, period))"""
            )
            conn.execute(
                "INSERT INTO budgets (id, user_id, space, category, amount, currency, period, created_at) "
                "SELECT id, user_id, 'Personal', category, amount, currency, period, created_at FROM budgets_old"
            )
            conn.execute("DROP TABLE budgets_old")

        # user_prefs gained tutorial_done.
        pcols = {row["name"] for row in conn.execute("PRAGMA table_info(user_prefs)")}
        if pcols and "tutorial_done" not in pcols:
            conn.execute("ALTER TABLE user_prefs ADD COLUMN tutorial_done INTEGER DEFAULT 0")
        if pcols and "digest_enabled" not in pcols:
            conn.execute("ALTER TABLE user_prefs ADD COLUMN digest_enabled INTEGER DEFAULT 0")
        if pcols and "briefing_enabled" not in pcols:
            conn.execute("ALTER TABLE user_prefs ADD COLUMN briefing_enabled INTEGER DEFAULT 0")
        if pcols and "active_list" not in pcols:
            conn.execute("ALTER TABLE user_prefs ADD COLUMN active_list TEXT")
        if pcols and "active_list_budget" not in pcols:
            conn.execute("ALTER TABLE user_prefs ADD COLUMN active_list_budget REAL")
        if pcols and "currency" not in pcols:
            conn.execute("ALTER TABLE user_prefs ADD COLUMN currency TEXT")
        if pcols and "wrapped_enabled" not in pcols:
            conn.execute("ALTER TABLE user_prefs ADD COLUMN wrapped_enabled INTEGER DEFAULT 0")
        if pcols and "referred_by" not in pcols:
            conn.execute("ALTER TABLE user_prefs ADD COLUMN referred_by TEXT")

        # shopping_items gained a per-item quantity.
        scols = {row["name"] for row in conn.execute("PRAGMA table_info(shopping_items)")}
        if scols and "quantity" not in scols:
            conn.execute("ALTER TABLE shopping_items ADD COLUMN quantity REAL DEFAULT 1")
        if scols and "category" not in scols:
            conn.execute("ALTER TABLE shopping_items ADD COLUMN category TEXT")

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
        currency: Optional[str] = None,
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
        if currency:
            clauses.append("COALESCE(currency, 'GBP') = ?")
            params.append(currency)

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

    def void_all_records(self, user_id: str, space: Optional[str] = None) -> int:
        """Soft-void every active record for a user (optionally one space).
        Returns the number of records voided. Audit rows are kept."""
        now = datetime.now().isoformat()
        clauses = ["user_id = ?", "COALESCE(voided, 0) = 0"]
        params: List[Any] = [user_id]
        if space:
            clauses.append("COALESCE(space, 'Personal') = ?")
            params.append(space)
        where = " AND ".join(clauses)
        with self._conn() as conn:
            cur = conn.execute(
                f"UPDATE records SET voided = 1, updated_at = ? WHERE {where}",
                [now] + params,
            )
            return cur.rowcount

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
        space: str = "Personal",
    ) -> None:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO budgets (id, user_id, space, category, amount, currency, period, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, space, category, period) DO UPDATE SET amount=excluded.amount
                """,
                (str(uuid.uuid4()), user_id, space, category, amount, currency, period, now),
            )

    def delete_budget(self, user_id: str, category: str, period: str = "monthly",
                      space: str = "Personal") -> int:
        """Delete a budget by category (case-insensitive). Returns rows removed."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM budgets WHERE user_id=? AND COALESCE(space,'Personal')=? "
                "AND lower(category)=lower(?) AND period=?",
                (user_id, space, category, period),
            )
            return cur.rowcount

    def delete_all_budgets(self, user_id: str, period: str = "monthly",
                           space: str = "Personal") -> int:
        """Delete every budget in a space. Returns rows removed."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM budgets WHERE user_id=? AND COALESCE(space,'Personal')=? AND period=?",
                (user_id, space, period),
            )
            return cur.rowcount

    def rename_budget(self, user_id: str, old_category: str, new_category: str,
                      period: str = "monthly", space: str = "Personal") -> bool:
        """Rename a budget's category, keeping its amount/currency. Returns True if
        a matching budget was found and renamed."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT amount, currency FROM budgets WHERE user_id=? AND COALESCE(space,'Personal')=? "
                "AND lower(category)=lower(?) AND period=?",
                (user_id, space, old_category, period),
            ).fetchone()
            if not row:
                return False
            conn.execute(
                "DELETE FROM budgets WHERE user_id=? AND COALESCE(space,'Personal')=? "
                "AND lower(category)=lower(?) AND period=?",
                (user_id, space, old_category, period),
            )
            import uuid as _uuid
            conn.execute(
                """INSERT INTO budgets (id, user_id, space, category, amount, currency, period, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, space, category, period) DO UPDATE SET amount=excluded.amount,
                   currency=excluded.currency""",
                (str(_uuid.uuid4()), user_id, space, new_category, row["amount"], row["currency"],
                 period, datetime.now().isoformat()),
            )
            return True

    def get_budgets(self, user_id: str, period: str = "monthly",
                    space: Optional[str] = None) -> List[Dict[str, Any]]:
        clauses = ["user_id = ?", "period = ?"]
        params: List[Any] = [user_id, period]
        if space:
            clauses.append("COALESCE(space, 'Personal') = ?")
            params.append(space)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM budgets WHERE {' AND '.join(clauses)}", params,
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

    def get_tutorial_done(self, user_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT tutorial_done FROM user_prefs WHERE user_id = ?", (user_id,)
            ).fetchone()
        return bool(row and row["tutorial_done"])

    # -------------------------------------------------------------------------
    # Reminder opt-ins (daily digest / morning briefing)
    # -------------------------------------------------------------------------

    _REMINDER_COLS = {"digest": "digest_enabled", "briefing": "briefing_enabled",
                      "wrapped": "wrapped_enabled"}

    def set_reminder(self, user_id: str, kind: str, enabled: bool) -> None:
        col = self._REMINDER_COLS[kind]
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO user_prefs (user_id, {col}) VALUES (?, ?) "
                f"ON CONFLICT(user_id) DO UPDATE SET {col} = excluded.{col}",
                (user_id, 1 if enabled else 0),
            )

    def get_reminders(self, user_id: str) -> Dict[str, bool]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT digest_enabled, briefing_enabled, wrapped_enabled FROM user_prefs WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return {
            "digest": bool(row and row["digest_enabled"]),
            "briefing": bool(row and row["briefing_enabled"]),
            "wrapped": bool(row and row["wrapped_enabled"]),
        }

    def set_referred_by(self, user_id: str, referrer: str) -> bool:
        """Record who referred a user, once (ignored if already set or self). True if stored."""
        if not referrer or referrer == user_id:
            return False
        with self._conn() as conn:
            row = conn.execute("SELECT referred_by FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
            if row and row["referred_by"]:
                return False
            conn.execute(
                "INSERT INTO user_prefs (user_id, referred_by) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET referred_by = excluded.referred_by",
                (user_id, referrer),
            )
            return True

    def list_reminder_users(self, kind: str) -> List[str]:
        col = self._REMINDER_COLS[kind]
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT user_id FROM user_prefs WHERE {col} = 1"
            ).fetchall()
        return [r["user_id"] for r in rows]

    def set_tutorial_done(self, user_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO user_prefs (user_id, tutorial_done) VALUES (?, 1) "
                "ON CONFLICT(user_id) DO UPDATE SET tutorial_done = 1",
                (user_id,),
            )

    # -------------------------------------------------------------------------
    # Shopping / price lists
    # -------------------------------------------------------------------------

    def get_active_list(self, user_id: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute("SELECT active_list FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
        return row["active_list"] if row and row["active_list"] else None

    def set_active_list(self, user_id: str, list_name: Optional[str]) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO user_prefs (user_id, active_list) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET active_list = excluded.active_list",
                (user_id, list_name),
            )
            # Closing a list clears its trip budget.
            if list_name is None:
                conn.execute("UPDATE user_prefs SET active_list_budget = NULL WHERE user_id = ?", (user_id,))

    def get_active_list_budget(self, user_id: str) -> Optional[float]:
        with self._conn() as conn:
            row = conn.execute("SELECT active_list_budget FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
        return row["active_list_budget"] if row and row["active_list_budget"] is not None else None

    def set_active_list_budget(self, user_id: str, amount: Optional[float]) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO user_prefs (user_id, active_list_budget) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET active_list_budget = excluded.active_list_budget",
                (user_id, amount),
            )

    def get_currency_pref(self, user_id: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute("SELECT currency FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
        return row["currency"] if row and row["currency"] else None

    def set_currency_pref(self, user_id: str, code: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO user_prefs (user_id, currency) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET currency = excluded.currency",
                (user_id, code),
            )

    def add_shopping_item(self, user_id: str, space: str, list_name: str,
                          item: str, amount: Optional[float], currency: str = "GBP",
                          quantity: float = 1, category: Optional[str] = None) -> None:
        import secrets
        import time
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO shopping_items (id, user_id, space, list_name, item, amount, quantity, category, currency, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (secrets.token_hex(8), user_id, space, list_name, item, amount, quantity, category, currency, time.time()),
            )

    def get_shopping_items(self, user_id: str, space: str, list_name: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM shopping_items WHERE user_id=? AND COALESCE(space,'Personal')=? AND lower(list_name)=lower(?) "
                "ORDER BY created_at",
                (user_id, space, list_name),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_shopping_lists(self, user_id: str, space: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT list_name, COUNT(*) AS n, COALESCE(SUM(amount * COALESCE(quantity, 1)),0) AS total "
                "FROM shopping_items WHERE user_id=? AND COALESCE(space,'Personal')=? GROUP BY list_name",
                (user_id, space),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_shopping_item(self, user_id: str, space: str, list_name: str,
                             item_keyword: str, amount: float) -> Optional[str]:
        """Update the price of the most recent item matching a keyword. Returns its name."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, item FROM shopping_items WHERE user_id=? AND COALESCE(space,'Personal')=? "
                "AND lower(list_name)=lower(?) AND lower(item) LIKE ? ORDER BY created_at DESC LIMIT 1",
                (user_id, space, list_name, f"%{item_keyword.lower()}%"),
            ).fetchone()
            if not row:
                return None
            conn.execute("UPDATE shopping_items SET amount=? WHERE id=?", (amount, row["id"]))
            return row["item"]

    def update_shopping_quantity(self, user_id: str, space: str, list_name: str,
                                 item_keyword: str, qty: Optional[float] = None,
                                 delta: Optional[float] = None) -> Optional[Tuple[str, float]]:
        """Set or adjust the quantity of the most recent matching item.

        Pass `qty` to set an absolute count, or `delta` to add/subtract. The
        quantity is floored at 1. Returns (item_name, new_qty) or None if no match.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, item, COALESCE(quantity, 1) AS quantity FROM shopping_items "
                "WHERE user_id=? AND COALESCE(space,'Personal')=? AND lower(list_name)=lower(?) "
                "AND lower(item) LIKE ? ORDER BY created_at DESC LIMIT 1",
                (user_id, space, list_name, f"%{item_keyword.lower()}%"),
            ).fetchone()
            if not row:
                return None
            new_qty = qty if qty is not None else (row["quantity"] + (delta or 0))
            new_qty = max(1, new_qty)
            conn.execute("UPDATE shopping_items SET quantity=? WHERE id=?", (new_qty, row["id"]))
            return row["item"], new_qty

    def delete_shopping_item(self, user_id: str, space: str, list_name: str,
                             item_keyword: str) -> Optional[str]:
        """Delete the most recent item matching a keyword. Returns its name."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, item FROM shopping_items WHERE user_id=? AND COALESCE(space,'Personal')=? "
                "AND lower(list_name)=lower(?) AND lower(item) LIKE ? ORDER BY created_at DESC LIMIT 1",
                (user_id, space, list_name, f"%{item_keyword.lower()}%"),
            ).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM shopping_items WHERE id=?", (row["id"],))
            return row["item"]

    def clear_shopping_list(self, user_id: str, space: str, list_name: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM shopping_items WHERE user_id=? AND COALESCE(space,'Personal')=? AND lower(list_name)=lower(?)",
                (user_id, space, list_name),
            )
            return cur.rowcount

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

"""Tests for the session stores (in-memory and SQLite-backed)."""

import time

from openclaw.integrations.session_store import SessionStore, SqliteSessionStore


def test_inmemory_put_get_pop():
    s = SessionStore()
    token = s.put({"a": 1})
    assert s.get(token) == {"a": 1}
    assert s.pop(token) == {"a": 1}
    assert s.get(token) is None


def test_sqlite_survives_new_instance(tmp_path):
    db = str(tmp_path / "s.db")
    token = SqliteSessionStore(db).put({"action": "DELETE_EXISTING", "candidates": [{"id": "x"}]})
    # Simulate a restart: brand-new store object, same DB file.
    revived = SqliteSessionStore(db)
    payload = revived.get(token)
    assert payload is not None
    assert payload["candidates"][0]["id"] == "x"


def test_sqlite_ttl_expiry(tmp_path):
    s = SqliteSessionStore(str(tmp_path / "s.db"), ttl_seconds=0)
    token = s.put({"a": 1})
    time.sleep(0.01)
    assert s.get(token) is None

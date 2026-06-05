"""Tests for SQLite storage adapter."""

import pytest
from datetime import datetime
from openclaw.storage.sqlite_adapter import SQLiteAdapter


@pytest.fixture
def db(tmp_path):
    return SQLiteAdapter(str(tmp_path / "test.db"))


SAMPLE_RECORD = {
    "domain": "finance",
    "type": "expense",
    "amount": 4.50,
    "currency": "GBP",
    "description": "Coffee",
    "raw_input": "Coffee £4.50",
    "entities": {"category": "Food & Drink"},
    "confidence": 0.9,
    "timestamp": "2026-06-04T10:00:00",
    "user_id": "user1",
}


class TestSQLiteAdapter:
    def test_insert_and_retrieve(self, db):
        rid = db.insert_record(dict(SAMPLE_RECORD))
        record = db.get_record(rid)
        assert record is not None
        assert record["amount"] == pytest.approx(4.50)

    def test_query_by_domain(self, db):
        db.insert_record(dict(SAMPLE_RECORD))
        records = db.query_records(domain="finance", user_id="user1")
        assert len(records) >= 1

    def test_query_by_type(self, db):
        db.insert_record(dict(SAMPLE_RECORD))
        records = db.query_records(domain="finance", record_type="expense", user_id="user1")
        assert all(r["type"] == "expense" for r in records)

    def test_sum_amount(self, db):
        r1 = dict(SAMPLE_RECORD)
        r2 = dict(SAMPLE_RECORD)
        r2["amount"] = 10.0
        db.insert_record(r1)
        db.insert_record(r2)
        total = db.sum_amount("finance", user_id="user1")
        assert total == pytest.approx(14.50)

    def test_budget_upsert(self, db):
        db.upsert_budget("user1", "Food & Drink", 200.0, "monthly")
        budgets = db.get_budgets("user1", "monthly")
        assert len(budgets) == 1
        assert budgets[0]["amount"] == 200.0

    def test_budget_update(self, db):
        db.upsert_budget("user1", "Food & Drink", 200.0, "monthly")
        db.upsert_budget("user1", "Food & Drink", 300.0, "monthly")
        budgets = db.get_budgets("user1", "monthly")
        assert len(budgets) == 1
        assert budgets[0]["amount"] == 300.0

    def test_date_range_filter(self, db):
        r = dict(SAMPLE_RECORD)
        r["timestamp"] = "2026-01-15T10:00:00"
        db.insert_record(r)

        # Query within range — should find it
        results = db.query_records(
            domain="finance", user_id="user1",
            since="2026-01-01T00:00:00", until="2026-01-31T23:59:59",
        )
        assert len(results) >= 1

        # Query outside range — should not find it
        results = db.query_records(
            domain="finance", user_id="user1",
            since="2026-02-01T00:00:00", until="2026-02-28T23:59:59",
        )
        assert len(results) == 0

    def test_idempotent_schema_init(self, tmp_path):
        """Creating adapter twice on same DB must not error."""
        path = str(tmp_path / "idempotent.db")
        SQLiteAdapter(path)
        SQLiteAdapter(path)  # Should not raise

"""Tests for daily digest / morning briefing content + reminder opt-ins."""

from datetime import datetime, timedelta

import pytest

from openclaw.domains.finance.finance_plugin import FinancePlugin
from openclaw.storage.sqlite_adapter import SQLiteAdapter


@pytest.fixture
def db(tmp_path):
    return SQLiteAdapter(str(tmp_path / "t.db"))


@pytest.fixture
def fp(db):
    return FinancePlugin(db, default_user="u")


def _ins(db, amt, desc, cat, when, user="u", cur="GBP"):
    db.insert_record({"domain": "finance", "type": "expense", "amount": amt, "currency": cur,
                      "description": desc, "entities": {"category": cat}, "timestamp": when.isoformat(),
                      "user_id": user, "confidence": 0.9, "space": "Personal"})


class TestReminderOptIns:
    def test_default_off(self, db):
        r = db.get_reminders("u")
        assert r == {"digest": False, "briefing": False}

    def test_toggle_and_list(self, db):
        db.set_reminder("u", "digest", True)
        db.set_reminder("v", "briefing", True)
        assert db.get_reminders("u")["digest"] is True
        assert db.list_reminder_users("digest") == ["u"]
        assert db.list_reminder_users("briefing") == ["v"]
        db.set_reminder("u", "digest", False)
        assert db.list_reminder_users("digest") == []

    def test_toggle_preserves_active_space(self, db):
        db.set_active_space("u", "Business")
        db.set_reminder("u", "digest", True)
        assert db.get_active_space("u") == "Business"


class TestDigest:
    def test_today_digest(self, fp, db):
        now = datetime.now()
        _ins(db, 14.20, "Tesco", "Groceries", now)
        _ins(db, 9.30, "Costa", "Food & Drink", now)
        out = fp.daily_digest("u")
        assert "📊 Today" in out
        assert "£23.50" in out           # 14.20 + 9.30
        assert "Tesco" in out            # biggest spend surfaced
        assert "£14.20" in out

    def test_digest_empty_is_positive(self, fp):
        out = fp.daily_digest("u")
        assert "No spending logged today" in out

    def test_digest_with_budget_remaining(self, fp, db):
        db.upsert_budget("u", "Groceries", 100.0, "monthly", space="Personal")
        _ins(db, 30.0, "Tesco", "Groceries", datetime.now())
        out = fp.daily_digest("u")
        assert "Budget left this month" in out
        assert "£70.00" in out


class TestBriefing:
    def test_yesterday_and_month(self, fp, db):
        now = datetime.now()
        _ins(db, 12.0, "lunch", "Food & Drink", now - timedelta(days=1))
        _ins(db, 5.0, "coffee", "Food & Drink", now)
        out = fp.morning_briefing("u")
        assert "Good morning" in out
        assert "Yesterday you spent £12.00" in out
        assert "This month so far" in out

    def test_briefing_no_fabricated_balance(self, fp):
        out = fp.morning_briefing("u")
        # We never invent a balance/forecast we can't compute.
        assert "balance" not in out.lower()
        assert "forecast" not in out.lower()

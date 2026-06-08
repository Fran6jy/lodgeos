"""Tests for the LLM query-plan fallback and subscription detection."""

from datetime import datetime, timedelta

import pytest

from openclaw.core.agent_orchestrator import AgentOrchestrator
from openclaw.core.router import Router
from openclaw.domains.finance.finance_plugin import FinancePlugin
from openclaw.llm.anthropic_client import MockLLMClient
from openclaw.storage.sqlite_adapter import SQLiteAdapter


def _ins(db, amt, desc, cat, when, rtype="expense", user="default"):
    db.insert_record({"domain": "finance", "type": rtype, "amount": amt, "currency": "GBP",
                      "description": desc, "entities": {"category": cat}, "timestamp": when.isoformat(),
                      "user_id": user, "confidence": 0.9, "space": "Personal"})


@pytest.fixture
def db(tmp_path):
    return SQLiteAdapter(str(tmp_path / "t.db"))


@pytest.fixture
def orch(db):
    fin = FinancePlugin(db, default_user="default")
    r = Router(); r.register("finance", fin); r.register("general", fin)
    return AgentOrchestrator(llm_client=MockLLMClient(), router=r)


class TestLLMFallback:
    def test_largest_expense_via_planner(self, orch, db):
        now = datetime.now()
        _ins(db, 12.0, "coffee", "Food & Drink", now)
        _ins(db, 80.0, "new jacket", "Shopping", now)
        # 'biggest' is not a deterministic pattern -> goes to the planner.
        out = orch.answer("What's my biggest purchase this month?")
        assert "80" in out and "jacket" in out.lower()

    def test_count_via_planner(self, orch, db):
        now = datetime.now()
        _ins(db, 3.0, "coffee", "Food & Drink", now)
        _ins(db, 3.5, "coffee", "Food & Drink", now)
        out = orch.answer("How many times did I buy coffee?")
        assert "2 transactions" in out

    def test_deterministic_path_still_used(self, orch, db):
        _ins(db, 10.0, "lunch", "Food & Drink", datetime.now())
        out = orch.answer("How much have I spent this month?")
        assert "£10.00" in out


class TestSubscriptions:
    def test_detects_recurring_charge(self, db):
        fp = FinancePlugin(db, default_user="default")
        now = datetime.now()
        # Same merchant + amount across two months -> recurring.
        _ins(db, 9.99, "Netflix subscription", "Entertainment", now)
        _ins(db, 9.99, "Netflix subscription", "Entertainment", now - timedelta(days=31))
        out = fp.detect_subscriptions()
        assert "Netflix" in out
        assert "9.99" in out

    def test_no_subscriptions_graceful(self, db):
        fp = FinancePlugin(db, default_user="default")
        _ins(db, 4.0, "one-off snack", "Food & Drink", datetime.now())
        assert "No recurring" in fp.detect_subscriptions()

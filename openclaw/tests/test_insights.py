"""Tests for Spending Insights (month-over-month) and correction re-categorization."""

import pytest
from datetime import datetime, timedelta

from openclaw.core.agent_orchestrator import AgentOrchestrator
from openclaw.core.router import Router
from openclaw.domains.finance.finance_plugin import FinancePlugin
from openclaw.llm.anthropic_client import MockLLMClient
from openclaw.storage.sqlite_adapter import SQLiteAdapter


@pytest.fixture
def db(tmp_path):
    return SQLiteAdapter(str(tmp_path / "t.db"))


@pytest.fixture
def plugin(db):
    return FinancePlugin(db, default_user="u")


@pytest.fixture
def orch(db):
    finance = FinancePlugin(db, default_user="default")
    router = Router()
    router.register("finance", finance)
    router.register("general", finance)
    return AgentOrchestrator(llm_client=MockLLMClient(), router=router)


def _insert(db, amount, cat, when, user="u"):
    db.insert_record({
        "domain": "finance", "type": "expense", "amount": amount, "currency": "GBP",
        "description": cat, "entities": {"category": cat}, "timestamp": when.isoformat(),
        "user_id": user, "confidence": 0.9, "space": "Personal",
    })


class TestSpendingInsights:
    def test_empty_is_graceful(self, plugin):
        assert "No spending" in plugin.spending_insights()

    def test_month_over_month_increase(self, plugin, db):
        now = datetime.now()
        last_month = (now.replace(day=1) - timedelta(days=5))
        _insert(db, 50.0, "Food & Drink", last_month)
        _insert(db, 84.0, "Food & Drink", now)
        out = plugin.spending_insights()
        assert "Food & Drink" in out
        assert "%" in out  # shows a percentage change vs last month

    def test_top_category_surfaced(self, plugin, db):
        now = datetime.now()
        _insert(db, 67.0, "Groceries", now)
        _insert(db, 10.0, "Transport", now)
        out = plugin.spending_insights()
        assert "Groceries" in out


class TestCorrectionRecategorization:
    def test_description_change_recategorizes(self, orch):
        orch.process("Spent £30 on stuff")          # -> Other
        # Simulate the classifier returning a new description but no category.
        orch.corrector.classify = lambda *a, **k: {
            "intent": "UPDATE_EXISTING",
            "target_search_criteria": {"approximate_old_amount": 30.0, "old_description_keyword": None},
            "updates": {"description": "facebook ads", "amount": None, "category": None},
        }
        r = orch.process("Actually that was facebook ads")
        assert r.success
        # the corrected description re-routes to Marketing automatically
        assert r.record["entities"]["category"] == "Marketing"

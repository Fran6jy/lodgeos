"""Tests for natural-language budget setting (not recorded as an expense)."""

import pytest

from openclaw.core.agent_orchestrator import AgentOrchestrator
from openclaw.core.router import Router
from openclaw.domains.finance.finance_plugin import FinancePlugin
from openclaw.llm.anthropic_client import MockLLMClient
from openclaw.storage.sqlite_adapter import SQLiteAdapter


@pytest.fixture
def orch(tmp_path):
    db = SQLiteAdapter(str(tmp_path / "t.db"))
    fin = FinancePlugin(db, default_user="default")
    r = Router(); r.register("finance", fin); r.register("general", fin)
    return AgentOrchestrator(llm_client=MockLLMClient(), router=r)


def test_set_budget_with_amount(orch):
    r = orch.process("Set budget for Tea 50")
    assert r.success and "Budget set" in r.response and "Tea" in r.response
    budgets = orch._storage().get_budgets("default", "monthly", space="Personal")
    assert any(b["category"] == "Tea" and b["amount"] == 50 for b in budgets)
    # And it was NOT recorded as an expense.
    assert orch._storage().query_records(domain="finance", record_type="expense", user_id="default") == []


def test_set_budget_without_amount_asks(orch):
    # The screenshot bug: "Set budget for tea" with no amount must not record an expense.
    r = orch.process("Set budget for tea, amount's not known yet")
    assert not r.success
    assert "what monthly limit for Tea" in r.response
    assert orch._storage().query_records(domain="finance", record_type="expense", user_id="default") == []


def test_budget_for_phrasing(orch):
    r = orch.process("budget £200 for Groceries monthly")
    assert r.success and "Groceries" in r.response
    budgets = orch._storage().get_budgets("default", "monthly", space="Personal")
    assert any(b["category"] == "Groceries" and b["amount"] == 200 for b in budgets)


def test_budget_keeps_its_currency(orch):
    # A £ budget must store and report in £, even for a naira-default user.
    orch.process("Set budget for Food 100£")
    budgets = orch._storage().get_budgets("default", "monthly", space="Personal")
    food = next(b for b in budgets if b["category"] == "Food & Drink")
    assert food["amount"] == 100 and food["currency"] == "GBP"
    report = orch.router._registry["finance"]._budget_report("default", space="Personal")
    assert "£100.00" in report and "₦100.00" not in report


def test_budget_category_canonicalised(orch):
    # A recognised category snaps to the standard name so budgets reconcile with
    # auto-categorised spending; an unknown name stays as a custom category.
    orch.process("Set budget for food 80")
    orch.process("Set budget for per diems 120")
    cats = {b["category"] for b in orch._storage().get_budgets("default", "monthly", space="Personal")}
    assert "Food & Drink" in cats and "Food" not in cats
    assert "Per Diems" in cats


def test_normal_expense_not_hijacked(orch):
    r = orch.process("Spent £5 on a budget airline snack")
    assert r.success
    recs = orch._storage().query_records(domain="finance", record_type="expense", user_id="default")
    assert len(recs) == 1  # recorded as an expense, not a budget command

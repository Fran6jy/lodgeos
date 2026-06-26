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


def test_expense_attributed_to_named_budget(orch):
    orch.process("Set budget for Yi Shaun Costs 209£")
    r = orch.process("I spent 10£ on Monday and 35£ on Tuesday from the Yi Shaun Costs budget")
    assert r.success
    recs = orch._storage().query_records(domain="finance", record_type="expense", user_id="default", limit=10)
    assert len(recs) == 2
    assert all(rec["entities"]["category"] == "Yi Shaun Costs" for rec in recs)
    # the budget now shows the spend instead of £0
    report = orch.router._registry["finance"]._budget_report("default", space="Personal")
    assert "Yi Shaun Costs" in report and "£45.00" in report


def test_spend_in_named_budget_not_set_as_budget(orch):
    # "Spent in karate budget 10£ plus 20£" must log 2 expenses against the
    # Karate Costs budget, NOT create a new budget.
    orch.process("Set budget for Karate Costs 209£")
    r = orch.process("Spent in karate budget 10£ plus 20£")
    assert r.success
    recs = orch._storage().query_records(domain="finance", record_type="expense", user_id="default", limit=10)
    assert len(recs) == 2
    assert all(rec["entities"]["category"] == "Karate Costs" for rec in recs)
    # no stray budget got created from this message
    cats = [b["category"] for b in orch._storage().get_budgets("default", "monthly")]
    assert cats.count("Karate Costs") == 1
    assert not any("karate plus" in c.lower() for c in cats)


def test_budget_router_precedence(orch):
    # All four budget intents resolved by the single router, no cross-talk.
    # set
    orch.process("set budget for tea 300")
    # convert a list (distinct categories)
    orch.process("start a market list: rice 100, bus fare 50 [transport]")
    orch.process("convert the market list to a budget")
    # trip budget on an open list
    orch.process("start a party list: cake 40")
    r_trip = orch.process("budget 200")
    assert "Budget" in r_trip.response and "200" in r_trip.response
    # log against a named budget
    orch.process("spent 25 from the tea budget")
    budgets = {b["category"]: b["amount"] for b in orch._storage().get_budgets("default", "monthly")}
    assert budgets["Tea"] == 300                # set, not overwritten by the spend
    assert budgets["Transport"] == 50           # from the conversion
    assert budgets["Groceries"] == 100          # rice, from the conversion
    recs = orch._storage().query_records(domain="finance", record_type="expense", user_id="default")
    assert any(r["entities"]["category"] == "Tea" and r["amount"] == 25 for r in recs)


def test_delete_budget(orch):
    orch.process("set budget for fuel 200")
    orch.process("set budget for tea 50")
    r = orch.process("delete the fuel budget")
    assert "Deleted" in r.response
    cats = [b["category"] for b in orch._storage().get_budgets("default", "monthly")]
    assert cats == ["Tea"]          # only the fuel/Transport budget went


def test_delete_budget_unknown_asks(orch):
    r = orch.process("delete the cinema budget")
    assert not r.success and "Which budget" in r.response


def test_show_budgets_query(orch):
    orch.process("set budget for food 100")
    r = orch.process("show me my budgets")
    assert r.success and "Food" in r.response and "/mo" in r.response
    # The report is HTML (<b>/<code>) — it must be flagged so the bot sends it
    # with parse_mode="HTML" instead of leaking raw tags into the chat.
    assert r.html is True and "<b>" in r.response
    # not recorded as a note
    assert orch._storage().query_records(domain="finance", record_type="expense", user_id="default") == []


def test_greeting_not_recorded(orch):
    for g in ("Hello", "Hi", "good morning", "thanks"):
        r = orch.process(g)
        assert not r.success and "Hi!" in r.response
    assert orch._storage().query_records(user_id="default") == []


def test_rename_budget(orch):
    orch.process("set budget for food 100")
    r = orch.process("rename the food budget to groceries")
    assert "Renamed" in r.response
    cats = {b["category"]: b["amount"] for b in orch._storage().get_budgets("default", "monthly")}
    assert cats == {"Groceries": 100}      # amount preserved, old gone


def test_delete_all_budgets_confirms_then_clears(orch):
    orch.process("set budget for food 100")
    orch.process("set budget for transport 50")
    r = orch.process("delete all budgets")
    assert not r.success and r.pending["action"] == "CLEAR_BUDGETS"
    assert len(orch._storage().get_budgets("default", "monthly")) == 2   # nothing gone yet
    res = orch.apply_clear_budgets("default", r.pending["space"])
    assert "Deleted 2" in res.response
    assert orch._storage().get_budgets("default", "monthly") == []


def test_budget_report_layout(orch):
    orch.process("set budget for transport 50")
    orch.process("spent 30 on bus")
    report = orch.router._registry["finance"]._budget_report("default", space="Personal")
    assert "Transport</b> · £50.00/mo" in report
    assert "£30.00 spent · <b>£20.00 left</b>" in report
    assert "█" in report and "60%" in report     # progress bar present


def test_budget_report_over_budget(orch):
    orch.process("set budget for transport 50")
    orch.process("spent 70 on taxi")
    report = orch.router._registry["finance"]._budget_report("default", space="Personal")
    assert "over</b>" in report and "⚠️" in report


def test_vague_message_nudges_not_recorded(orch):
    # An unparseable message gets a how-to nudge, not a stored junk note.
    r = orch.process("asdf qwerty zzz")
    assert not r.success and "didn't quite catch" in r.response
    assert orch._storage().query_records(user_id="default") == []


def test_normal_expense_not_hijacked(orch):
    r = orch.process("Spent £5 on a budget airline snack")
    assert r.success
    recs = orch._storage().query_records(domain="finance", record_type="expense", user_id="default")
    assert len(recs) == 1  # recorded as an expense, not a budget command

"""Tests for the natural-language shopping / price-list feature."""

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


def _items(orch, name, space="Personal"):
    return orch._storage().get_shopping_items("default", space, name)


class TestShoppingFlow:
    def test_create_with_inline_items(self, orch):
        r = orch.process("start a chai list: ginger 500, milk 1200, cardamom 800")
        assert r.success and "Chai" in r.response
        items = _items(orch, "Chai")
        assert len(items) == 3
        assert {round(i["amount"]) for i in items} == {500, 1200, 800}
        # active list is set so follow-ups drop in
        assert orch._storage().get_active_list("default") == "Chai"

    def test_followup_items_added_in_mode(self, orch):
        orch.process("start a chai list")
        r = orch.process("ginger 500, milk 1200")
        assert r.success
        assert len(_items(orch, "Chai")) == 2
        # bare items were NOT recorded as expenses
        assert orch._storage().query_records(domain="finance", record_type="expense", user_id="default") == []

    def test_update_price(self, orch):
        orch.process("start a chai list: cardamom 800")
        r = orch.process("cardamom is actually 700")
        assert r.success
        items = _items(orch, "Chai")
        assert items[0]["amount"] == 700

    def test_show_lists(self, orch):
        orch.process("start a zobo list: hibiscus 300")
        r = orch.process("my lists")
        assert "Zobo" in r.response

    def test_bought_converts_to_expense_and_clears(self, orch):
        orch.process("start a chai list: ginger 500, milk 1200, cardamom 800")
        r = orch.process("bought chai")
        assert r.success and "Bought" in r.response
        # list cleared
        assert _items(orch, "Chai") == []
        # one Groceries expense for the total (2500)
        recs = orch._storage().query_records(domain="finance", record_type="expense", user_id="default")
        assert len(recs) == 1
        assert recs[0]["amount"] == pytest.approx(2500.0)
        assert recs[0]["entities"]["category"] == "Groceries"

    def test_per_item_quantity(self, orch):
        orch.process("start a chai list")
        r = orch.process("3 ginger at 250, milk 1200")
        assert r.success
        items = {i["item"]: i for i in _items(orch, "Chai")}
        assert items["Ginger"]["quantity"] == 3
        assert items["Ginger"]["amount"] == 250          # stored as unit price
        assert items["Milk"]["quantity"] == 1
        # buying logs unit*qty: 3*250 + 1200 = 1950
        orch.process("bought chai")
        recs = orch._storage().query_records(domain="finance", record_type="expense", user_id="default")
        assert recs[0]["amount"] == pytest.approx(1950.0)

    def test_add_does_not_leak_list_name_into_item(self, orch):
        orch.process("start a chai list: ginger 500")
        orch.process("add star anise to the chai list 100")
        names = {i["item"] for i in _items(orch, "Chai")}
        assert "Star Anise" in names
        assert "Star Anise Chai" not in names

    def test_quantity_x_notation(self, orch):
        orch.process("start a chai list")
        orch.process("ginger x2 250")
        assert _items(orch, "Chai")[0]["quantity"] == 2

    def _qty(self, orch, name, item):
        return next(i["quantity"] for i in _items(orch, name) if i["item"] == item)

    def test_quantity_edit_set_and_increment(self, orch):
        orch.process("start a chai list: 3 ginger at 250")
        orch.process("make ginger 2")
        assert self._qty(orch, "Chai", "Ginger") == 2
        orch.process("add 3 more ginger")
        assert self._qty(orch, "Chai", "Ginger") == 5
        orch.process("2 less ginger")
        assert self._qty(orch, "Chai", "Ginger") == 3

    def test_inline_trip_budget_and_overflow(self, orch):
        r = orch.process("start a market list, budget 1000: 3 ginger at 250")
        assert orch._storage().get_active_list_budget("default") == 1000
        # 3*250 = 750 estimated → 250 left
        assert "left" in r.response
        r2 = orch.process("add 2 tomatoes 200")  # +400 → 1150, over by 150
        assert "over by" in r2.response
        # budget cleared once the list is bought
        orch.process("bought market")
        assert orch._storage().get_active_list_budget("default") is None

    def test_buy_splits_into_categories(self, orch):
        orch.process("start a trip list: rice 500, bus fare 200")
        orch.process("bought trip")
        recs = orch._storage().query_records(domain="finance", record_type="expense", user_id="default")
        by_cat = {r["entities"]["category"]: r["amount"] for r in recs}
        assert by_cat.get("Transport") == pytest.approx(200)   # bus fare
        assert by_cat.get("Groceries") == pytest.approx(500)   # rice (market default)

    def test_explicit_category_tag(self, orch):
        orch.process("start a trip list: rice 500, phone charger 5000 [shopping]")
        orch.process("bought trip")
        recs = orch._storage().query_records(domain="finance", record_type="expense", user_id="default")
        by_cat = {r["entities"]["category"]: r["amount"] for r in recs}
        assert by_cat.get("Shopping") == pytest.approx(5000)   # tagged
        assert by_cat.get("Groceries") == pytest.approx(500)   # rice default

    def test_list_to_budget_then_buy(self, orch):
        orch.process("start a market list: rice 500, bus fare 200 [transport]")
        r = orch.process("convert the market list to a budget")
        assert r.success and "budget" in r.response.lower()
        budgets = {b["category"]: b["amount"]
                   for b in orch._storage().get_budgets("default", "monthly", space="Personal")}
        assert budgets.get("Groceries") == pytest.approx(500)
        assert budgets.get("Transport") == pytest.approx(200)
        # list still exists for later
        assert len(_items(orch, "Market")) == 2
        # now buy it → expenses logged, list cleared
        orch.process("bought market")
        assert _items(orch, "Market") == []

    def test_finance_budget_not_hijacked_by_list(self, orch):
        # An open list must not swallow a real category-budget command.
        orch.process("start a chai list: ginger 500")
        r = orch.process("set tea budget to 50")
        assert "budget" in r.response.lower()
        # the trip budget was NOT set from this
        assert orch._storage().get_active_list_budget("default") is None

    def test_budget_for_category_not_hijacked_by_list(self, orch):
        # "set budget for food 100" names a category → finance, not the trip budget.
        orch.process("start a ogbono list: palm oil 500")
        orch.process("set budget for food 100")
        # trip budget untouched; a real (category) budget was created instead
        assert orch._storage().get_active_list_budget("default") is None
        cats = {b["category"] for b in orch._storage().get_budgets("default", "monthly")}
        assert any("food" in c.lower() for c in cats)

    def test_set_budget_not_caught_by_list_converter(self, orch):
        # "set budget for fuel 209" with a list open must create a finance budget,
        # not be read as "convert this list into a budget".
        orch.process("start a ogbono list: palm oil 500")
        orch.process("set budget for fuel costs 209")
        cats = {b["category"] for b in orch._storage().get_budgets("default", "monthly")}
        assert any("fuel" in c.lower() or "transport" in c.lower() for c in cats)
        # the ogbono list's per-category budget was NOT created from a conversion
        assert "Groceries" not in cats

    def test_remove_single_item(self, orch):
        orch.process("start a chai list: ginger 500, milk 1200, cardamom 800")
        r = orch.process("remove milk from the chai list")
        assert r.success and "Removed" in r.response
        names = {i["item"] for i in _items(orch, "Chai")}
        assert names == {"Ginger", "Cardamom"}
        # not misrouted to an expense/inventory record
        assert orch._storage().query_records(user_id="default") == []

    def test_add_to_new_named_trip(self, orch):
        # "add X to the Malta trip" creates a Malta list and doesn't leak the
        # list name into the item.
        orch.process("Add plane ticket 450 to the Malta trip")
        items = _items(orch, "Malta")
        assert len(items) == 1
        assert items[0]["item"] == "Plane Ticket"
        assert round(items[0]["amount"]) == 450

    def test_add_to_named_trip_ignores_active_list(self, orch):
        orch.process("start a chai list: ginger 500")
        orch.process("add plane ticket 450 to the Malta trip")
        assert {i["item"] for i in _items(orch, "Malta")} == {"Plane Ticket"}
        assert {i["item"] for i in _items(orch, "Chai")} == {"Ginger"}   # untouched

    def test_open_list_does_not_swallow_a_correction(self, orch):
        orch.process("start a zobo list: hibiscus 300")
        # A correction to a past expense must not become a list item.
        sig = orch.shopping.handle("Actually that transport was 50", "default", "Personal")
        assert sig is None
        assert {i["item"] for i in _items(orch, "Zobo")} == {"Hibiscus"}

    def test_open_list_does_not_swallow_a_ledger_delete(self, orch):
        orch.process("start a zobo list: hibiscus 300")
        # "delete the 3 transport" targets expenses, not the open list → defer.
        assert orch.shopping.handle("Delete the 3 transport", "default", "Personal") is None
        # a real list removal (bare item that exists) still works
        assert orch.shopping.handle("remove hibiscus", "default", "Personal")[0] == "reply"

    def test_delete_shopping_list_with_word_shopping(self, orch):
        orch.process("start a chai list: ginger 500")
        r = orch.process("delete the chai shopping list")
        assert "Cleared" in r.response
        assert _items(orch, "Chai") == []

    def test_show_list_does_not_invent_name(self, orch):
        orch.process("start a chai list: ginger 500")
        r = orch.process("show me my shopping list")
        # shows the open Chai list, not a phantom "Show Me"
        assert "Chai" in r.response and "Show Me" not in r.response

    def test_clear_list(self, orch):
        orch.process("start a chai list: ginger 500")
        r = orch.process("clear chai list")
        assert "Cleared" in r.response
        assert _items(orch, "Chai") == []

    def test_not_in_mode_is_normal_expense(self, orch):
        # No list open → an ordinary expense, not a list item.
        r = orch.process("Spent £5 on coffee")
        assert r.success
        assert len(orch._storage().query_records(domain="finance", record_type="expense", user_id="default")) == 1
        assert orch._storage().get_active_list("default") is None

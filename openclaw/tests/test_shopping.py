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

    def test_quantity_x_notation(self, orch):
        orch.process("start a chai list")
        orch.process("ginger x2 250")
        assert _items(orch, "Chai")[0]["quantity"] == 2

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

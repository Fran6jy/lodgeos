"""Tests for Financial Memory — answering natural-language questions."""

from datetime import datetime

import pytest

from openclaw.domains.finance.finance_plugin import FinancePlugin
from openclaw.storage.sqlite_adapter import SQLiteAdapter


@pytest.fixture
def plugin(tmp_path):
    db = SQLiteAdapter(str(tmp_path / "t.db"))
    fp = FinancePlugin(db, default_user="u")
    now = datetime.now().isoformat()
    for amt, desc, cat in [(67.0, "Tesco shop", "Groceries"),
                           (12.0, "coffee at Nero", "Food & Drink"),
                           (30.0, "Tesco again", "Groceries")]:
        db.insert_record({"domain": "finance", "type": "expense", "amount": amt, "currency": "GBP",
                          "description": desc, "entities": {"category": cat}, "timestamp": now,
                          "user_id": "u", "confidence": 0.9, "space": "Personal"})
    db.insert_record({"domain": "finance", "type": "income", "amount": 200.0, "currency": "GBP",
                      "description": "client", "entities": {"category": "Freelance"}, "timestamp": now,
                      "user_id": "u", "confidence": 0.9, "space": "Personal"})
    return fp


def test_total_spent_this_month(plugin):
    out = plugin.answer_question("How much have I spent this month?")
    assert "£109.00" in out  # 67 + 12 + 30

def test_spend_by_category(plugin):
    out = plugin.answer_question("How much on Groceries this month?")
    assert "Groceries" in out and "£97.00" in out  # 67 + 30

def test_spend_at_merchant(plugin):
    out = plugin.answer_question("How much have I spent at Tesco?")
    assert "Tesco" in out and "£97.00" in out

def test_income_question(plugin):
    out = plugin.answer_question("How much income this month?")
    assert "£200.00" in out

def test_biggest_area(plugin):
    out = plugin.answer_question("Where does my money go?")
    assert "Groceries" in out

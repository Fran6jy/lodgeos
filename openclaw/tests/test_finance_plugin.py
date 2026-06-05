"""Tests for the Finance plugin."""

import pytest
from datetime import datetime
from openclaw.domains.finance.finance_plugin import FinancePlugin, _infer_category
from openclaw.storage.sqlite_adapter import SQLiteAdapter
from openclaw.tests.sample_dataset import EXPECTED_CATEGORIES


@pytest.fixture
def db(tmp_path):
    return SQLiteAdapter(str(tmp_path / "test.db"))


@pytest.fixture
def plugin(db):
    return FinancePlugin(db, default_user="test_user")


@pytest.fixture
def expense_record():
    return {
        "domain": "finance",
        "type": "expense",
        "amount": 4.50,
        "currency": "GBP",
        "description": "Coffee at Nero",
        "raw_input": "Spent £4.50 at Nero for coffee",
        "entities": {"merchant": "Nero", "category": None},
        "confidence": 0.92,
        "timestamp": datetime.now().isoformat(),
        "user_id": "test_user",
    }


class TestCategoryInference:
    def test_coffee_is_food_drink(self):
        assert _infer_category("coffee at Nero") == "Food & Drink"

    def test_uber_is_transport(self):
        assert _infer_category("Uber to work") == "Transport"

    def test_amazon_is_shopping(self):
        assert _infer_category("bought from Amazon") == "Shopping"

    def test_supermarket_is_groceries(self):
        assert _infer_category("weekly shop at Tesco") == "Groceries"
        assert _infer_category("groceries from Lidl") == "Groceries"

    def test_netflix_is_entertainment(self):
        assert _infer_category("Netflix subscription") == "Entertainment"

    def test_unknown_is_other(self):
        assert _infer_category("random thing") == "Other"

    def test_salary_is_salary(self):
        assert _infer_category("salary payment") == "Salary"

    def test_chocolate_is_food_drink(self):
        # Regression: "20 pounds chocolate" was previously mis-categorised as "Other".
        assert _infer_category("I just bought a 20 pounds chocolate") == "Food & Drink"

    @pytest.mark.parametrize("message,expected", list(EXPECTED_CATEGORIES.items()))
    def test_expected_categories(self, message, expected):
        assert _infer_category(message) == expected

    def test_category_accuracy_meets_threshold(self):
        """Success metric: categorizer must hit the spec's 95% accuracy bar."""
        correct = sum(
            _infer_category(msg) == expected
            for msg, expected in EXPECTED_CATEGORIES.items()
        )
        accuracy = correct / len(EXPECTED_CATEGORIES)
        assert accuracy >= 0.95, f"Category accuracy {accuracy:.0%} below 95% target"


class TestFinancePluginTransform:
    def test_infers_category_when_null(self, plugin, expense_record):
        result = plugin.transform(expense_record)
        assert result["entities"]["category"] == "Food & Drink"

    def test_preserves_existing_category(self, plugin, expense_record):
        expense_record["entities"]["category"] = "Transport"
        result = plugin.transform(expense_record)
        assert result["entities"]["category"] == "Transport"

    def test_sets_default_currency(self, plugin, expense_record):
        del expense_record["currency"]
        result = plugin.transform(expense_record)
        assert result["currency"] == "GBP"

    def test_sets_timestamp_if_missing(self, plugin, expense_record):
        expense_record["timestamp"] = None
        result = plugin.transform(expense_record)
        assert result["timestamp"] is not None


class TestFinancePluginStore:
    def test_stores_and_retrieves(self, plugin, db, expense_record):
        plugin.transform(expense_record)
        record_id = plugin.store(expense_record)
        retrieved = db.get_record(record_id)
        assert retrieved is not None
        assert retrieved["amount"] == pytest.approx(4.50)

    def test_multiple_records_stored(self, plugin, db, expense_record):
        for i in range(5):
            r = dict(expense_record)
            r["amount"] = float(i + 1)
            r.pop("id", None)
            plugin.transform(r)
            plugin.store(r)

        records = db.query_records(domain="finance", user_id="test_user")
        assert len(records) >= 5


class TestFinancePluginSummarize:
    def test_summarize_returns_string(self, plugin, db, expense_record):
        plugin.transform(expense_record)
        plugin.store(expense_record)
        summary = plugin.summarize("week")
        assert isinstance(summary, str)
        assert "Finance Summary" in summary

    def test_summarize_empty_period(self, plugin):
        summary = plugin.summarize("month")
        assert "No records found" in summary


class TestBudgets:
    def test_set_and_get_budget(self, plugin, db):
        result = plugin.set_budget("Food & Drink", 200.0, "monthly")
        assert "200.00" in result
        budgets = db.get_budgets("test_user", "monthly")
        assert len(budgets) == 1
        assert budgets[0]["category"] == "Food & Drink"

    def test_budget_report_empty(self, plugin):
        result = plugin._budget_report()
        assert "No budgets set" in result

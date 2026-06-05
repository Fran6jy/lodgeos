"""Tests for intent classification and entity extraction."""

import json
import pytest
from unittest.mock import MagicMock

from openclaw.core.intent_parser import IntentParser
from openclaw.llm.anthropic_client import MockLLMClient


SAMPLE_MESSAGES = [
    ("Spent £4.50 at Nero for coffee", "expense", "finance", 4.50),
    ("Coffee at Costa £3.20", "expense", "finance", 3.20),
    ("Paid £45 for Uber", "expense", "finance", 45.0),
    ("Bought groceries at Tesco £67.30", "expense", "finance", 67.30),
    ("Received salary £3200", "income", "finance", 3200.0),
    ("Client paid invoice £500", "income", "finance", 500.0),
    ("Spent £12 on lunch", "expense", "finance", 12.0),
]


@pytest.fixture
def parser():
    return IntentParser(MockLLMClient())


class TestIntentClassification:
    def test_expense_classified(self, parser):
        record = parser.parse("Spent £4.50 at Nero for coffee")
        assert record["type"] in ("expense", "general_note")
        assert record["domain"] in ("finance", "general")

    def test_income_classified(self, parser):
        record = parser.parse("Received salary £3200")
        assert record["type"] in ("income", "general_note")

    def test_timestamp_always_set(self, parser):
        record = parser.parse("Spent £10 at Tesco")
        assert record.get("timestamp") is not None

    def test_explicit_dollar_overrides_default_currency(self, parser):
        # Regression: "$10" must record USD, not the default GBP.
        record = parser.parse("I just bought $10 shoes")
        assert record["amount"] == pytest.approx(10.0)
        assert record["currency"] == "USD"

    def test_euro_symbol_detected(self, parser):
        record = parser.parse("Spent €20 on lunch")
        assert record["currency"] == "EUR"

    def test_confidence_range(self, parser):
        record = parser.parse("Spent £10 at Tesco")
        assert 0.0 <= record["confidence"] <= 1.0

    def test_amount_extracted(self, parser):
        record = parser.parse("Spent £4.50 at Nero for coffee")
        assert record.get("amount") == pytest.approx(4.50, abs=0.01)

    def test_entities_dict(self, parser):
        record = parser.parse("Spent £4.50 at Nero")
        assert isinstance(record.get("entities"), dict)

    def test_raw_input_preserved(self, parser):
        msg = "Spent £4.50 at Nero for coffee"
        record = parser.parse(msg)
        assert record.get("raw_input") == msg


class TestRegressionSuite:
    """Regression tests on sample messages."""

    @pytest.mark.parametrize("msg,expected_type,expected_domain,expected_amount", SAMPLE_MESSAGES)
    def test_sample_messages(self, parser, msg, expected_type, expected_domain, expected_amount):
        record = parser.parse(msg)
        # Amount should be extracted (either by LLM or fallback)
        assert record.get("amount") == pytest.approx(expected_amount, abs=0.01), \
            f"Amount mismatch for: {msg}"
        assert record.get("timestamp") is not None


class TestJsonParsing:
    def test_strips_markdown_fences(self):
        raw = '```json\n{"key": "value"}\n```'
        result = IntentParser._parse_json(raw)
        assert result == {"key": "value"}

    def test_handles_plain_json(self):
        raw = '{"key": "value"}'
        result = IntentParser._parse_json(raw)
        assert result == {"key": "value"}

    def test_returns_empty_on_invalid(self):
        result = IntentParser._parse_json("not json at all")
        assert result == {}

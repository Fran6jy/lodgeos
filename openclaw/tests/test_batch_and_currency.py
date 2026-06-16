"""Tests for batch (multi-line) entry and non-GBP currency support (NGN etc.)."""

import pytest

from openclaw.core.agent_orchestrator import AgentOrchestrator
from openclaw.core.router import Router
from openclaw.domains.finance.finance_plugin import FinancePlugin
from openclaw.llm.anthropic_client import MockLLMClient
from openclaw.storage.sqlite_adapter import SQLiteAdapter
from openclaw.utils.currency_normalizer import extract_amount_and_currency, format_amount

FRIEND_MESSAGE = """Spendings;
1. Withdrew 5,000 naira for transport to school and others.
2. Went to the cafe to print and sent 1800 to the cafe lady for snacks and printing.
3. Paid 35,000 at the transcript office
4. Sent 10,000 to the someone at the transcript office
5. Sent another 10,000 to someone in the registry"""


@pytest.fixture
def orch(tmp_path):
    db = SQLiteAdapter(str(tmp_path / "t.db"))
    fin = FinancePlugin(db, default_user="default")
    r = Router(); r.register("finance", fin); r.register("general", fin)
    return AgentOrchestrator(llm_client=MockLLMClient(), router=r)


class TestCurrencyWords:
    def test_naira_word(self):
        assert extract_amount_and_currency("Withdrew 5,000 naira for transport") == (5000.0, "NGN")

    def test_naira_symbol(self):
        assert extract_amount_and_currency("spent ₦1,800 on snacks") == (1800.0, "NGN")

    def test_pounds_word(self):
        assert extract_amount_and_currency("bought 20 pounds chocolate") == (20.0, "GBP")

    def test_dollars_word(self):
        assert extract_amount_and_currency("10 dollars on shoes") == (10.0, "USD")

    def test_ngn_formats_with_symbol(self):
        assert format_amount(5000, "NGN") == "₦5,000.00"


class TestBatchEntry:
    def test_friend_message_records_all_five(self, orch):
        r = orch.process(FRIEND_MESSAGE)
        assert r.success
        recs = orch._storage().query_records(domain="finance", user_id="default", limit=20)
        assert len(recs) == 5
        # The naira stated in line 1 propagates to bare-number lines.
        assert all(rec["currency"] == "NGN" for rec in recs)
        amounts = sorted(rec["amount"] for rec in recs)
        assert amounts == [1800.0, 5000.0, 10000.0, 10000.0, 35000.0]
        assert "Recorded 5 entries" in r.response
        assert "₦61,800.00" in r.response

    def test_voice_paragraph_multiple_amounts_split(self, orch):
        # The screenshot bug: one spoken paragraph, no line breaks, 4 amounts.
        msg = ("5,000 naira we drew for transportation and snacks. The 5,000 naira paid "
               "to transcripts office. 10,000 naira given for fast tracking. "
               "Another 10,000 naira given at the registry.")
        r = orch.process(msg)
        assert r.success
        recs = orch._storage().query_records(domain="finance", user_id="default", limit=20)
        assert len(recs) == 4                       # NOT one merged ₦30,000
        assert all(rec["currency"] == "NGN" for rec in recs)
        assert sorted(rec["amount"] for rec in recs) == [5000.0, 5000.0, 10000.0, 10000.0]
        assert "Recorded 4 entries" in r.response

    def test_single_line_split_by_category(self, orch):
        # "10£ on rice and 20£ on food" → two expenses in their own categories.
        r = orch.process("I spent 10£ on rice and 20£ on the food budget")
        assert r.success
        recs = orch._storage().query_records(domain="finance", record_type="expense", user_id="default", limit=10)
        assert len(recs) == 2
        by_amt = {rec["amount"]: rec for rec in recs}
        assert by_amt[10.0]["currency"] == "GBP"
        assert by_amt[20.0]["entities"]["category"] == "Food & Drink"

    def test_single_line_not_batched(self, orch):
        r = orch.process("Spent £4.50 on coffee")
        assert r.success
        assert len(orch._storage().query_records(domain="finance", user_id="default", limit=10)) == 1

    def test_summary_shows_records_currency_not_gbp(self, orch):
        # Regression: a naira user's totals must show ₦, not a hardcoded £.
        orch.process(FRIEND_MESSAGE)
        fp = orch.router._registry["finance"]
        assert fp._user_currency("default") == "NGN"
        summary = fp.summarize("month", "default")
        assert "₦61,800.00" in summary
        assert "£" not in summary
        # Q&A totals too
        ans = orch.answer("how much have I spent this month?", "default")
        assert "₦" in ans and "£" not in ans

    def test_mixed_currency_summary_is_grouped_not_summed(self, orch):
        db = orch._storage()
        now = __import__("datetime").datetime.now().isoformat()
        for amt, cat, c in [(10, "Transport", "NGN"), (20, "Food & Drink", "NGN"), (2, "Entertainment", "USD")]:
            db.insert_record({"domain": "finance", "type": "expense", "amount": amt, "currency": c,
                              "description": cat, "entities": {"category": cat}, "timestamp": now,
                              "user_id": "default", "confidence": 0.9, "space": "Personal"})
        summary = orch.router._registry["finance"].summarize("week", "default")
        # Currencies shown separately, NEVER merged into one nonsense number.
        assert "₦30.00" in summary
        assert "$2.00" in summary
        assert "$32" not in summary and "$47" not in summary  # no cross-currency sum
        # Each category shown in its own currency
        assert "Transport            ₦10.00" in summary
        assert "Entertainment        $2.00" in summary

    def test_batch_without_currency_defaults_gbp(self, orch):
        r = orch.process("1. Spent 10 on lunch\n2. Spent 5 on coffee")
        assert r.success
        recs = orch._storage().query_records(domain="finance", user_id="default", limit=10)
        assert len(recs) == 2
        assert all(rec["currency"] == "GBP" for rec in recs)

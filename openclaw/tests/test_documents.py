"""Tests for image/document parsing into transactions."""

import json
import pytest

from openclaw.core.agent_orchestrator import AgentOrchestrator
from openclaw.core.router import Router
from openclaw.domains.finance.finance_plugin import FinancePlugin
from openclaw.llm.anthropic_client import MockLLMClient, MockVisionClient
from openclaw.storage.sqlite_adapter import SQLiteAdapter


def _orch(tmp_path, vision_response=None):
    db = SQLiteAdapter(str(tmp_path / "t.db"))
    finance = FinancePlugin(db, default_user="default")
    router = Router()
    router.register("finance", finance)
    router.register("general", finance)
    vision = MockVisionClient(vision_response)
    return AgentOrchestrator(llm_client=MockLLMClient(), router=router, vision_client=vision)


class TestDocumentParsing:
    def test_receipt_becomes_expense(self, tmp_path):
        orch = _orch(tmp_path)
        r = orch.process_document("ZmFrZQ==")  # canned MockVisionClient → Tesco £2.15 Groceries
        assert r.success
        assert r.record["type"] == "expense"
        assert r.record["amount"] == pytest.approx(2.15)
        assert r.record["entities"]["category"] == "Groceries"
        assert "🧾" in r.response

    def test_payslip_becomes_income(self, tmp_path):
        resp = json.dumps({"action": "RECORD_NEW", "type": "income", "amount": 1850.0,
                           "currency": "GBP", "description": "Net pay — payslip", "category": "Income"})
        orch = _orch(tmp_path, resp)
        r = orch.process_document("ZmFrZQ==")
        assert r.success and r.record["type"] == "income"
        assert r.record["amount"] == pytest.approx(1850.0)

    def test_refund_is_negative(self, tmp_path):
        resp = json.dumps({"action": "RECORD_NEW", "type": "expense", "amount": -19.99,
                           "currency": "GBP", "description": "REFUND — returned shoes", "category": "Shopping"})
        orch = _orch(tmp_path, resp)
        r = orch.process_document("ZmFrZQ==")
        assert r.success
        assert r.record["amount"] == pytest.approx(-19.99)
        assert "refund" in r.response.lower() and "£19.99" in r.response

    def test_refund_offsets_totals(self, tmp_path):
        orch = _orch(tmp_path, json.dumps({"action": "RECORD_NEW", "type": "expense", "amount": -10.0,
                     "currency": "GBP", "description": "REFUND", "category": "Shopping"}))
        # Record a £30 expense, then a -£10 refund → net £20 spent.
        orch.process("Spent £30 on clothes")
        orch.process_document("ZmFrZQ==")
        db = orch._storage()
        assert db.sum_amount("finance", "expense", "default") == pytest.approx(20.0)

    def test_no_vision_client_is_graceful(self, tmp_path):
        db = SQLiteAdapter(str(tmp_path / "t.db"))
        finance = FinancePlugin(db)
        router = Router(); router.register("finance", finance); router.register("general", finance)
        orch = AgentOrchestrator(llm_client=MockLLMClient(), router=router)  # no vision
        r = orch.process_document("ZmFrZQ==")
        assert not r.success and "isn't configured" in r.response

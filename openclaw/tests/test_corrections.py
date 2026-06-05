"""Tests for the correction layer: soft-void, update, and search."""

import pytest

from openclaw.core.agent_orchestrator import AgentOrchestrator
from openclaw.core.router import Router
from openclaw.domains.finance.finance_plugin import FinancePlugin
from openclaw.llm.anthropic_client import MockLLMClient
from openclaw.storage.sqlite_adapter import SQLiteAdapter


@pytest.fixture
def db(tmp_path):
    return SQLiteAdapter(str(tmp_path / "t.db"))


@pytest.fixture
def orchestrator(db):
    finance = FinancePlugin(db, default_user="default")
    router = Router()
    router.register("finance", finance)
    router.register("general", finance)
    return AgentOrchestrator(llm_client=MockLLMClient(), router=router)


# --- Storage-level ----------------------------------------------------------

class TestStorageCorrections:
    def _insert(self, db, amount, desc, cat="Food & Drink"):
        rec = {"domain": "finance", "type": "expense", "amount": amount, "currency": "GBP",
               "description": desc, "entities": {"category": cat}, "timestamp": "2026-06-04T10:00:00",
               "user_id": "u", "confidence": 0.9}
        return db.insert_record(rec)

    def test_void_excludes_from_totals(self, db):
        rid = self._insert(db, 10.0, "coffee")
        assert db.sum_amount("finance", "expense", "u") == pytest.approx(10.0)
        assert db.void_record(rid) is True
        assert db.sum_amount("finance", "expense", "u") == pytest.approx(0.0)

    def test_voided_excluded_from_query(self, db):
        rid = self._insert(db, 5.0, "snack")
        db.void_record(rid)
        assert db.query_records(user_id="u") == []
        # but still retrievable for audit
        assert db.query_records(user_id="u", include_voided=True)

    def test_update_changes_amount_and_keeps_history(self, db):
        rid = self._insert(db, 4.50, "coffee")
        updated = db.update_record(rid, {"amount": 6.0})
        assert updated["amount"] == 6.0
        assert updated["_history"][0]["previous"]["amount"] == 4.50

    def test_search_by_amount(self, db):
        self._insert(db, 4.50, "coffee")
        self._insert(db, 30.0, "petrol", "Transport")
        hits = db.search_records(user_id="u", approx_amount=4.50)
        assert len(hits) == 1 and hits[0]["description"] == "coffee"


# --- End-to-end through the orchestrator ------------------------------------

class TestOrchestratorCorrections:
    def test_new_entry_is_not_a_correction(self, orchestrator):
        r = orchestrator.process("Spent £4.50 on coffee")
        assert r.success and r.record["type"] == "expense"

    def test_update_amount(self, orchestrator):
        orchestrator.process("Spent £4.50 on coffee")
        r = orchestrator.process("Actually that coffee was £6")
        assert r.success
        assert "Updated" in r.response
        assert r.record["amount"] == pytest.approx(6.0)

    def test_delete_voids_entry(self, orchestrator):
        orchestrator.process("Spent £4.50 on coffee")
        r = orchestrator.process("Delete the £4.50 coffee")
        assert r.success
        assert "Voided" in r.response
        # totals now zero
        assert orchestrator._storage().sum_amount("finance", "expense", "default") == pytest.approx(0.0)

    def test_correction_with_no_match(self, orchestrator):
        r = orchestrator.process("Delete the £999 yacht")
        assert not r.success
        assert "couldn't find" in r.response.lower()

    def test_ambiguous_update_returns_pending_candidates(self, orchestrator):
        orchestrator.process("Spent £5 on coffee")
        orchestrator.process("Spent £5 on tea")
        # No amount given -> matches multiple recent -> should offer a choice
        r = orchestrator.process("Actually that should be shopping")
        assert "multiple" in r.response.lower()
        assert r.pending is not None
        assert len(r.pending["candidates"]) == 2
        assert r.pending["action"] == "UPDATE_EXISTING"

    def test_hallucinated_keyword_is_ignored(self, orchestrator):
        # Two real £5 entries; a third stale one whose description contains "cream".
        orchestrator.process("Spent £5 on coffee")
        orchestrator.process("Spent £5 on tea")
        orchestrator._storage().insert_record({
            "domain": "finance", "type": "expense", "amount": 5.0, "currency": "GBP",
            "description": "If I spend 5pounds for cream how much is left",
            "entities": {"category": "Other"}, "timestamp": "2026-06-01T10:00:00",
            "user_id": "default", "confidence": 0.5,
        })
        # Simulate a noisy model that invents a keyword absent from the message.
        orchestrator.corrector.classify = lambda *a, **k: {
            "intent": "DELETE_EXISTING",
            "target_search_criteria": {"approximate_old_amount": 5.0, "old_description_keyword": "cream"},
        }
        r = orchestrator.process("Delete the £5 one")
        # The bogus keyword must be dropped -> still ambiguous -> buttons, NOT a silent void.
        assert r.pending is not None
        assert len(r.pending["candidates"]) == 3

    def test_apply_correction_to_chosen_candidate(self, orchestrator):
        orchestrator.process("Spent £5 on coffee")
        orchestrator.process("Spent £5 on tea")
        r = orchestrator.process("Actually that should be transport")
        chosen = r.pending["candidates"][0]
        applied = orchestrator.apply_correction(
            record_id=chosen["id"], action="UPDATE_EXISTING",
            updates=r.pending["updates"], user_id="default",
        )
        assert applied.success
        assert applied.record["entities"]["category"] == "Transport"

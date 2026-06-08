"""Tests for Budget Spaces — per-record space tagging and isolation."""

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
def orch(db):
    finance = FinancePlugin(db, default_user="default")
    router = Router()
    router.register("finance", finance)
    router.register("general", finance)
    return AgentOrchestrator(llm_client=MockLLMClient(), router=router)


class TestStorageSpaces:
    def test_default_space_is_personal(self, db):
        assert db.get_active_space("u") == "Personal"

    def test_set_and_get_active_space(self, db):
        db.set_active_space("u", "Business")
        assert db.get_active_space("u") == "Business"

    def test_list_spaces_includes_defaults(self, db):
        assert "Personal" in db.list_spaces("u")
        assert "Business" in db.list_spaces("u")


class TestSpaceTagging:
    def test_prefix_sets_space(self, orch):
        r = orch.process("Business: Spent £30 on Facebook ads")
        assert r.record["space"] == "Business"
        # prefix is stripped from the stored description/amount parse
        assert r.record["amount"] == pytest.approx(30.0)

    def test_active_space_applies_without_prefix(self, orch):
        orch._storage().set_active_space("default", "Property")
        r = orch.process("Spent £120 on a plumber")
        assert r.record["space"] == "Property"

    def test_prefix_overrides_active_space(self, orch):
        orch._storage().set_active_space("default", "Property")
        r = orch.process("Business: Spent £15 on stamps")
        assert r.record["space"] == "Business"

    def test_note_prefix_is_not_a_space(self, orch):
        # 'Note:' is in the stoplist -> stays in the active (Personal) space.
        r = orch.process("Note: Spent £5 on coffee")
        assert r.record["space"] == "Personal"

    def test_unknown_prefix_is_not_hijacked(self, orch):
        # 'Lunch:' is not a known space -> must NOT become a space.
        r = orch.process("Lunch: Spent £12 today")
        assert r.record["space"] == "Personal"

    def test_custom_space_works_after_creation(self, orch):
        orch._storage().set_active_space("default", "Charity")  # creates/knows it
        orch._storage().set_active_space("default", "Personal")  # switch back
        r = orch.process("Charity: Spent £20 on a donation")
        assert r.record["space"] == "Charity"

    def test_summary_isolated_by_space(self, orch):
        orch.process("Business: Spent £30 on ads")
        orch.process("Spent £10 on coffee")  # Personal
        db = orch._storage()
        biz = db.sum_amount("finance", "expense", "default", space="Business")
        personal = db.sum_amount("finance", "expense", "default", space="Personal")
        assert biz == pytest.approx(30.0)
        assert personal == pytest.approx(10.0)

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

    def test_tutorial_flag(self, db):
        assert db.get_tutorial_done("u") is False
        db.set_tutorial_done("u")
        assert db.get_tutorial_done("u") is True
        # marking the tutorial done must not disturb the active space
        assert db.get_active_space("u") == "Personal"

    def test_tutorial_steps_render(self):
        from openclaw.integrations.telegram_bot import ui
        for i in range(4):
            text, kb = ui.tutorial(i)
            assert text and kb.inline_keyboard
        # out-of-range clamps, doesn't crash
        assert ui.tutorial(99)[0]

    def test_list_spaces_includes_defaults(self, db):
        assert "Personal" in db.list_spaces("u")
        assert "Business" in db.list_spaces("u")

    def test_budgets_are_per_space(self, db):
        # Same category, different budget per space — must not collide.
        db.upsert_budget("u", "Food & Drink", 50, "monthly", space="Personal")
        db.upsert_budget("u", "Food & Drink", 200, "monthly", space="Business")
        personal = db.get_budgets("u", "monthly", space="Personal")
        business = db.get_budgets("u", "monthly", space="Business")
        assert personal[0]["amount"] == 50
        assert business[0]["amount"] == 200
        assert len(db.get_budgets("u", "monthly")) == 2   # both, unscoped


class TestSpaceTagging:
    def test_prefix_sets_space(self, orch):
        r = orch.process("Business: Spent £30 on Facebook ads")
        assert r.record["space"] == "Business"
        # prefix is stripped from the stored description/amount parse
        assert r.record["amount"] == pytest.approx(30.0)

    def test_asks_current_space(self, orch):
        orch._storage().set_active_space("default", "Business")
        r = orch.process("what space am I in")
        assert r.success
        assert "Business" in r.response
        assert r.record is None

    def test_asks_current_space_with_typo(self, orch):
        orch._storage().set_active_space("default", "Property")
        r = orch.process("what space ami i in")
        assert r.success
        assert "Property" in r.response
        assert r.record is None

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

    def test_nl_space_switch_parsing(self, db):
        from openclaw.integrations.telegram_bot.bot import _parse_space_switch

        class _FP:
            def __init__(self, d): self.db = d
        fp = _FP(db)
        assert _parse_space_switch("Switch to personal space", fp, "u") == "Personal"
        assert _parse_space_switch("switch to business", fp, "u") == "Business"
        assert _parse_space_switch("go to property space", fp, "u") == "Property"
        # Not a switch command -> None (records normally)
        assert _parse_space_switch("Spent £5 on coffee", fp, "u") is None
        assert _parse_space_switch("Business: spent £30 on ads", fp, "u") is None

    def test_space_name_punctuation_normalised(self, db):
        # Regression: a voice-transcribed trailing '.' must not create 'Business .'
        from openclaw.integrations.telegram_bot.bot import _parse_space_switch, _normalize_space_name
        assert _normalize_space_name("business .") == "Business"
        assert _normalize_space_name("  side hustle, ") == "Side Hustle"

        class _FP:
            def __init__(self, d): self.db = d
        fp = _FP(db)
        # "switch to business space." (with period) resolves to existing "Business"
        assert _parse_space_switch("switch to business space.", fp, "u") == "Business"

    def test_summary_isolated_by_space(self, orch):
        orch.process("Business: Spent £30 on ads")
        orch.process("Spent £10 on coffee")  # Personal
        db = orch._storage()
        biz = db.sum_amount("finance", "expense", "default", space="Business")
        personal = db.sum_amount("finance", "expense", "default", space="Personal")
        assert biz == pytest.approx(30.0)
        assert personal == pytest.approx(10.0)

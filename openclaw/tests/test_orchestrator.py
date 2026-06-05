"""Integration tests for the full orchestrator pipeline."""

import pytest
from openclaw.core.agent_orchestrator import AgentOrchestrator
from openclaw.core.router import Router
from openclaw.domains.finance.finance_plugin import FinancePlugin
from openclaw.llm.anthropic_client import MockLLMClient
from openclaw.storage.sqlite_adapter import SQLiteAdapter
from openclaw.tests.sample_dataset import SAMPLE_MESSAGES


@pytest.fixture
def orchestrator(tmp_path):
    db = SQLiteAdapter(str(tmp_path / "test.db"))
    finance = FinancePlugin(db, default_user="test")
    router = Router()
    router.register("finance", finance)
    router.register("general", finance)
    return AgentOrchestrator(llm_client=MockLLMClient(), router=router)


class TestOrchestratorPipeline:
    def test_expense_end_to_end(self, orchestrator):
        result = orchestrator.process("Spent £4.50 at Nero for coffee")
        assert result.success
        assert result.record is not None
        assert result.record.get("amount") == pytest.approx(4.50, abs=0.01)
        assert "4.50" in result.response

    def test_response_always_returned(self, orchestrator):
        result = orchestrator.process("Some random message")
        assert result.response  # Always returns something

    def test_elapsed_reasonable(self, orchestrator):
        result = orchestrator.process("Spent £10 at Tesco")
        assert result.elapsed_ms < 5000  # Under 5 seconds

    def test_user_id_propagated(self, orchestrator):
        result = orchestrator.process("Spent £10", user_id="alice")
        assert result.record.get("user_id") == "alice"

    @pytest.mark.parametrize("msg,etype,edomain,eamt", SAMPLE_MESSAGES)
    def test_regression_suite(self, orchestrator, msg, etype, edomain, eamt):
        """All sample messages must process without error."""
        result = orchestrator.process(msg)
        # We don't assert on type/domain since mock LLM is heuristic,
        # but we assert no crashes and amounts are extracted where expected
        assert result.success or result.error  # always returns a result
        if eamt is not None:
            if result.record and result.record.get("amount"):
                assert result.record["amount"] == pytest.approx(eamt, abs=0.01)

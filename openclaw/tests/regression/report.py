"""
Regression Accuracy Report.

Runs every message in 100_messages.json through the full orchestrator pipeline
and measures the three accuracy axes the architecture cares about most:

    Domain Accuracy    — was it routed to the right domain?
    Intent Accuracy    — was the record type classified correctly?
    Category Accuracy   — was the spending category inferred correctly?

Run standalone for a human-readable report:

    python -m openclaw.tests.regression.report

Or import `run_regression()` from tests to assert on thresholds in CI.

By default this uses the offline, deterministic MockLLMClient so the report
runs without an API key. Pass a real client to benchmark production accuracy.
"""

import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from openclaw.core.agent_orchestrator import AgentOrchestrator
from openclaw.core.router import Router
from openclaw.domains.finance.finance_plugin import FinancePlugin
from openclaw.llm.anthropic_client import MockLLMClient
from openclaw.storage.sqlite_adapter import SQLiteAdapter

DATASET = Path(__file__).parent / "100_messages.json"


@dataclass
class RegressionReport:
    total: int = 0
    domain_correct: int = 0
    intent_correct: int = 0
    category_correct: int = 0
    avg_latency_ms: float = 0.0
    misses: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def domain_accuracy(self) -> float:
        return self.domain_correct / self.total if self.total else 0.0

    @property
    def intent_accuracy(self) -> float:
        return self.intent_correct / self.total if self.total else 0.0

    @property
    def category_accuracy(self) -> float:
        return self.category_correct / self.total if self.total else 0.0

    def render(self) -> str:
        lines = [
            "Regression Accuracy Report",
            "=" * 34,
            f"Messages:          {self.total}",
            f"Domain Accuracy:   {self.domain_accuracy:.0%}",
            f"Intent Accuracy:   {self.intent_accuracy:.0%}",
            f"Category Accuracy:  {self.category_accuracy:.0%}",
            f"Avg Latency:       {self.avg_latency_ms:.1f}ms",
        ]
        if self.misses:
            lines.append("")
            lines.append(f"Misses ({len(self.misses)}):")
            for m in self.misses:
                axes = ", ".join(m["wrong"])
                lines.append(f"  [{axes}] {m['message']!r}")
                for axis in m["wrong"]:
                    lines.append(f"      {axis}: expected {m['expected'][axis]!r}, got {m['actual'][axis]!r}")
        return "\n".join(lines)


def _load_dataset() -> List[Dict[str, Any]]:
    with open(DATASET, encoding="utf-8") as f:
        return json.load(f)


def run_regression(llm_client: Optional[Any] = None, db_path: Optional[str] = None) -> RegressionReport:
    """Run the dataset through the orchestrator and return a RegressionReport."""
    cases = _load_dataset()

    # A throwaway file-backed DB — the adapter opens a fresh connection per call,
    # so an in-memory (":memory:") DB would not persist the schema across calls.
    if db_path is None:
        db_path = str(Path(tempfile.mkdtemp()) / "regression.db")
    db = SQLiteAdapter(db_path)
    finance = FinancePlugin(db, default_user="regression")
    router = Router()
    router.register("finance", finance)
    router.register("general", finance)
    orchestrator = AgentOrchestrator(llm_client=llm_client or MockLLMClient(), router=router)

    report = RegressionReport(total=len(cases))
    latencies: List[float] = []

    for case in cases:
        start = time.perf_counter()
        result = orchestrator.process(case["message"])
        latencies.append((time.perf_counter() - start) * 1000)

        record = result.record or {}
        actual = {
            "domain": record.get("domain"),
            "type": record.get("type"),
            "category": record.get("entities", {}).get("category"),
        }
        expected = {
            "domain": case["domain"],
            "type": case["type"],
            "category": case["category"],
        }

        wrong = [axis for axis in ("domain", "type", "category") if actual[axis] != expected[axis]]
        if "domain" not in wrong:
            report.domain_correct += 1
        if "type" not in wrong:
            report.intent_correct += 1
        if "category" not in wrong:
            report.category_correct += 1
        if wrong:
            report.misses.append(
                {"message": case["message"], "wrong": wrong, "expected": expected, "actual": actual}
            )

    report.avg_latency_ms = sum(latencies) / len(latencies) if latencies else 0.0
    return report


def main() -> None:
    print(run_regression().render())


if __name__ == "__main__":
    main()

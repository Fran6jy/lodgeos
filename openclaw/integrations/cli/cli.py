"""
OpenClaw CLI — interactive command-line interface.

Usage:
    python -m openclaw.integrations.cli.cli
    python -m openclaw.integrations.cli.cli --mock   # use mock LLM (no API key needed)
    python -m openclaw.integrations.cli.cli --db /path/to/db.sqlite

Special commands (prefix with /):
    /summary [day|week|month]   — spending summary
    /budget                     — budget report
    /income                     — income summary
    /set budget <cat> <amount>  — set monthly budget
    /history [N]                — last N records (default 10)
    /help                       — show help
    /quit or /exit              — exit
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure package root is on path when run directly
_PKG_ROOT = str(Path(__file__).resolve().parents[3])
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from openclaw.core.agent_orchestrator import AgentOrchestrator
from openclaw.core.router import Router
from openclaw.domains.finance.finance_plugin import FinancePlugin
from openclaw.storage.sqlite_adapter import SQLiteAdapter
from openclaw.utils.currency_normalizer import format_amount

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BANNER = """
╔══════════════════════════════════════════════╗
║          OpenClaw — Record OS v0.1           ║
║   Natural Language → Structured Records      ║
╚══════════════════════════════════════════════╝
Type a message to record it, or /help for commands.
"""

HELP_TEXT = """
Commands:
  /summary [day|week|month]         — Finance summary
  /budget                           — Budget vs actual
  /income                           — Income this month
  /set budget <category> <amount>   — Set monthly budget
  /history [N]                      — Last N records
  /help                             — This help text
  /quit                             — Exit

Examples of natural language input:
  Spent £4.50 at Nero for coffee
  Received salary £3200
  Paid £45 for Uber
  Bought groceries at Tesco £67.30
"""


def build_orchestrator(db_path: str, use_mock: bool = False, api_key: str = None, dev: bool = False) -> AgentOrchestrator:
    db = SQLiteAdapter(db_path)
    finance = FinancePlugin(db)

    router = Router()
    router.register("finance", finance)
    router.register("general", finance)  # fallback

    from openclaw.llm.factory import build_llm_client
    llm = build_llm_client(use_mock=use_mock, api_key=api_key)

    return AgentOrchestrator(llm_client=llm, router=router, dev=dev)


def handle_command(cmd: str, orchestrator: AgentOrchestrator, finance_plugin: FinancePlugin) -> str:
    """Handle /commands. Return response string."""
    parts = cmd.strip().lstrip("/").split()
    if not parts:
        return ""

    verb = parts[0].lower()

    if verb in ("quit", "exit", "q"):
        print("Goodbye.")
        sys.exit(0)

    if verb == "help":
        return HELP_TEXT

    if verb == "summary":
        tf = parts[1] if len(parts) > 1 else "week"
        return finance_plugin.summarize(tf)

    if verb == "budget":
        return finance_plugin._budget_report()

    if verb == "income":
        return finance_plugin._income_summary()

    if verb == "history":
        n = int(parts[1]) if len(parts) > 1 else 10
        records = finance_plugin.db.query_records(domain="finance", limit=n)
        if not records:
            return "No records found."
        lines = [f"Last {min(n, len(records))} records:", ""]
        for r in records:
            ts = r.get("timestamp", "")[:16]
            amt = format_amount(r["amount"]) if r.get("amount") else "       "
            lines.append(f"  {ts}  {r.get('type', ''):12}  {amt}  {r.get('description', '')[:50]}")
        return "\n".join(lines)

    if verb == "set" and len(parts) >= 4 and parts[1].lower() == "budget":
        # /set budget <category> <amount>
        try:
            amount = float(parts[-1].replace("£", "").replace(",", ""))
            category = " ".join(parts[2:-1]).title()
            return finance_plugin.set_budget(category, amount, "monthly")
        except ValueError:
            return "Usage: /set budget <category> <amount>  e.g. /set budget Food & Drink 200"

    return f"Unknown command: {verb}. Type /help for commands."


def main():
    parser = argparse.ArgumentParser(description="OpenClaw CLI")
    parser.add_argument("--mock", action="store_true", help="Use mock LLM (no API key needed)")
    parser.add_argument("--db", default="openclaw.db", help="Path to SQLite database")
    parser.add_argument("--api-key", help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
    parser.add_argument("--dev", action="store_true", help="Developer mode: show confidence scores")
    args = parser.parse_args()

    print(BANNER)
    if args.mock:
        print("  [MOCK MODE — using built-in heuristic LLM, no API calls]\n")

    try:
        orchestrator = build_orchestrator(args.db, use_mock=args.mock, api_key=args.api_key, dev=args.dev)
        finance_plugin = orchestrator.router._registry.get("finance")
    except ImportError as e:
        print(f"Error: {e}")
        print("Install dependencies: pip install -r requirements.txt")
        sys.exit(1)

    print(f"Database: {Path(args.db).resolve()}")
    print("Ready. Enter a message or /help\n")

    while True:
        try:
            message = input("▶ ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not message:
            continue

        if message.startswith("/"):
            response = handle_command(message, orchestrator, finance_plugin)
            print(response)
            print()
            continue

        # Process natural language message
        result = orchestrator.process(message)
        if result.success:
            print(f"\n{result.response}")
            print(f"  [domain={result.domain} | {result.elapsed_ms:.0f}ms]\n")
        else:
            print(f"\n❌ {result.response}\n")


if __name__ == "__main__":
    main()

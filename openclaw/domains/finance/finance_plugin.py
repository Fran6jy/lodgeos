"""
Finance Domain Plugin — fully implemented Phase 1.

Handles:
- Expense recording with category assignment
- Income recording
- Budget tracking (weekly / monthly)
- Reporting: daily, weekly, monthly summaries
- Category breakdown
- Budget vs actual comparison
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from openclaw.plugins.base_plugin import BasePlugin
from openclaw.storage.sqlite_adapter import SQLiteAdapter
from openclaw.utils.currency_normalizer import format_amount
from openclaw.utils.date_parser import (
    current_month_range,
    current_week_range,
    format_display,
)

logger = logging.getLogger(__name__)

CATEGORY_KEYWORDS = {
    "Food & Drink": ["coffee", "cafe", "nero", "starbucks", "restaurant", "lunch", "dinner", "breakfast", "food", "eat", "pub", "bar", "takeaway", "pizza", "burger", "chocolate", "ice cream", "dessert", "snack", "snacks", "sweets", "candy", "drink", "drinks", "beer", "wine"],
    "Transport": ["uber", "bus", "train", "tube", "taxi", "fuel", "petrol", "parking", "tfl", "metro", "car"],
    "Utilities": ["electric", "gas", "water", "internet", "broadband", "phone", "bill", "utility"],
    "Groceries": ["tesco", "sainsbury", "asda", "waitrose", "lidl", "aldi", "morrisons", "supermarket", "groceries", "grocery"],
    "Shopping": ["amazon", "shop", "store", "clothes", "clothing", "ikea", "argos"],
    "Entertainment": ["cinema", "netflix", "spotify", "game", "ticket", "tickets", "theatre", "concert", "gym", "sport", "sports", "subscription"],
    "Health": ["doctor", "pharmacy", "medication", "dentist", "optician", "hospital", "prescription"],
    "Education": ["course", "book", "tuition", "school", "university", "training", "udemy", "study"],
    "Rent": ["rent", "landlord", "lease"],
    "Salary": ["salary", "wage", "payroll", "pay"],
    "Freelance": ["freelance", "invoice", "client payment", "consulting"],
    "Investment": ["investment", "dividend", "stock", "share", "crypto", "fund"],
}


def _infer_category(text: str) -> str:
    import re
    text_lower = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            # Word-boundary matching for every keyword so e.g. "train" does not
            # match "training" (Education) or "car" match "card".
            if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
                return category
    return "Other"


class FinancePlugin(BasePlugin):
    """Finance domain plugin: expenses, income, budgets, reporting."""

    domain = "finance"

    def __init__(self, db: SQLiteAdapter, default_user: str = "default"):
        self.db = db
        self.default_user = default_user

    # -------------------------------------------------------------------------
    # BasePlugin interface
    # -------------------------------------------------------------------------

    def validate(self, record: Dict[str, Any]) -> bool:
        if record.get("type") not in ("expense", "income"):
            return False
        # Negative amounts allowed (refunds/returns offset prior spend).
        return True

    def transform(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich record with inferred category and computed fields."""
        entities = record.setdefault("entities", {})

        # Infer category if not already set
        if not entities.get("category") or entities["category"] == "Other":
            text = record.get("raw_input", "") + " " + record.get("description", "")
            entities["category"] = _infer_category(text)

        # Normalise currency
        record.setdefault("currency", "GBP")

        # Ensure timestamp
        if not record.get("timestamp"):
            record["timestamp"] = datetime.now().isoformat()

        return record

    def store(self, record: Dict[str, Any]) -> str:
        return self.db.insert_record(record)

    def query(self, request: str) -> str:
        req = request.lower()
        user_id = self.default_user

        if any(w in req for w in ("week", "weekly", "this week")):
            return self.summarize("week", user_id=user_id)
        if any(w in req for w in ("month", "monthly", "this month")):
            return self.summarize("month", user_id=user_id)
        if any(w in req for w in ("today", "today's")):
            return self.summarize("day", user_id=user_id)
        if "budget" in req:
            return self._budget_report(user_id=user_id)
        if "income" in req:
            return self._income_summary(user_id=user_id)

        # Default: this week
        return self.summarize("week", user_id=user_id)

    def summarize(self, timeframe: str = "week", user_id: Optional[str] = None,
                  space: Optional[str] = None) -> str:
        uid = user_id or self.default_user
        now = datetime.now()

        if timeframe == "day":
            since = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            until = now.isoformat()
            label = "Today"
        elif timeframe == "week":
            s, e = current_week_range(now)
            since, until = s.isoformat(), e.isoformat()
            label = "This week"
        elif timeframe == "month":
            s, e = current_month_range(now)
            since, until = s.isoformat(), e.isoformat()
            label = "This month"
        else:
            since = None
            until = None
            label = "All time"

        expenses = self.db.query_records(
            domain="finance", record_type="expense",
            user_id=uid, since=since, until=until, limit=500, space=space,
        )
        income = self.db.query_records(
            domain="finance", record_type="income",
            user_id=uid, since=since, until=until, limit=500, space=space,
        )

        total_exp = sum(r.get("amount", 0) or 0 for r in expenses)
        total_inc = sum(r.get("amount", 0) or 0 for r in income)

        # Category breakdown
        by_cat: Dict[str, float] = {}
        for r in expenses:
            cat = r.get("entities", {}).get("category", "Other")
            by_cat[cat] = by_cat.get(cat, 0) + (r.get("amount", 0) or 0)

        scope = f" · {space}" if space else ""
        lines = [f"📊 {label} Finance Summary{scope}", ""]
        if total_exp > 0:
            lines.append(f"💸 Total Spent:  {format_amount(total_exp)}")
        if total_inc > 0:
            lines.append(f"💰 Total Income: {format_amount(total_inc)}")
        if total_exp > 0 and total_inc > 0:
            lines.append(f"📈 Net:          {format_amount(total_inc - total_exp)}")

        if by_cat:
            lines.append("")
            lines.append("By category:")
            for cat, amt in sorted(by_cat.items(), key=lambda x: -x[1]):
                lines.append(f"  {cat:<20} {format_amount(amt)}")

        if not expenses and not income:
            lines.append("No records found for this period.")

        return "\n".join(lines)

    def _range(self, timeframe: str, now: Optional[datetime] = None):
        now = now or datetime.now()
        if timeframe == "week":
            s, e = current_week_range(now)
        else:
            s, e = current_month_range(now)
        return s.isoformat(), e.isoformat()

    def category_breakdown(self, timeframe: str = "month", user_id: Optional[str] = None,
                           space: Optional[str] = None) -> Dict[str, float]:
        """Return {category: total_spent} for the timeframe, descending."""
        uid = user_id or self.default_user
        since, until = self._range(timeframe)
        expenses = self.db.query_records(domain="finance", record_type="expense",
                                         user_id=uid, since=since, until=until, limit=2000, space=space)
        by_cat: Dict[str, float] = {}
        for r in expenses:
            cat = r.get("entities", {}).get("category", "Other")
            by_cat[cat] = by_cat.get(cat, 0) + (r.get("amount", 0) or 0)
        return dict(sorted(by_cat.items(), key=lambda x: -x[1]))

    def category_transactions(self, category: str, timeframe: str = "month",
                              user_id: Optional[str] = None,
                              space: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return this timeframe's expense records for one category, newest first."""
        uid = user_id or self.default_user
        since, until = self._range(timeframe)
        expenses = self.db.query_records(domain="finance", record_type="expense",
                                         user_id=uid, since=since, until=until, limit=2000, space=space)
        return [r for r in expenses if r.get("entities", {}).get("category", "Other") == category]

    # -------------------------------------------------------------------------
    # Response builder
    # -------------------------------------------------------------------------

    @staticmethod
    def _transaction_id(record: Dict[str, Any]) -> str:
        """Human-friendly transaction reference, e.g. EXP-20260604-3f9a."""
        prefix = {"expense": "EXP", "income": "INC"}.get(record.get("type"), "TXN")
        ts = record.get("timestamp", "") or datetime.now().isoformat()
        date_part = ts[:10].replace("-", "")
        suffix = (record.get("id") or "")[:4] or "0000"
        return f"{prefix}-{date_part}-{suffix}"

    def build_response(self, record: Dict[str, Any], memory=None, dev: bool = False) -> str:
        rtype = record.get("type", "entry")
        amount = record.get("amount")
        currency = record.get("currency", "GBP")
        description = record.get("description", "")
        category = record.get("entities", {}).get("category", "")
        merchant = record.get("entities", {}).get("merchant", "")
        space = record.get("space", "Personal")
        ts = record.get("timestamp", "")

        lines = []

        if rtype == "expense":
            amt_str = format_amount(amount, currency) if amount is not None else "(no amount)"
            # Only append the merchant if the description doesn't already mention it.
            who = f" at {merchant}" if merchant and merchant.lower() not in description.lower() else ""
            lines.append(f"✅ Recorded expense: {description}{who} ({amt_str})")
            lines.append(f"   ID: {self._transaction_id(record)}")
            if category:
                lines.append(f"   Category: {category}")

            # Budget remaining
            if memory and amount:
                budget_info = self._budget_remaining(category, amount, memory)
                if budget_info:
                    lines.append(f"   {budget_info}")

        elif rtype == "income":
            amt_str = format_amount(amount, currency) if amount is not None else "(no amount)"
            lines.append(f"✅ Recorded income: {description} ({amt_str})")
            lines.append(f"   ID: {self._transaction_id(record)}")

        else:
            lines.append(f"✅ Recorded {rtype}: {description}")

        # Show the Space only when it's not the default, to avoid clutter.
        if space and space != "Personal":
            lines.append(f"   🗂 Space: {space}")

        # Confidence is only surfaced in developer mode to aid debugging.
        if dev and record.get("confidence") is not None:
            lines.append(f"   Confidence: {record['confidence'] * 100:.0f}%")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Budget management
    # -------------------------------------------------------------------------

    def set_budget(self, category: str, amount: float, period: str = "monthly", user_id: Optional[str] = None) -> str:
        uid = user_id or self.default_user
        self.db.upsert_budget(uid, category, amount, period)
        return f"Budget set: {category} — {format_amount(amount)} per {period}"

    def _budget_remaining(self, category: str, new_spend: float, memory) -> Optional[str]:
        """Return budget remaining string if a budget is set for this category."""
        try:
            uid = self.default_user
            budgets = self.db.get_budgets(uid, "monthly")
            for b in budgets:
                if b["category"].lower() == category.lower():
                    s, e = current_month_range()
                    spent = self.db.sum_amount(
                        domain="finance", record_type="expense",
                        user_id=uid, since=s.isoformat(), until=e.isoformat(),
                        category=category,
                    )
                    remaining = b["amount"] - spent
                    if remaining < 0:
                        return f"⚠️  Over budget by {format_amount(abs(remaining))} (budget: {format_amount(b['amount'])})"
                    return f"Monthly budget remaining ({category}): {format_amount(remaining)}"
        except Exception as e:
            logger.debug("Budget check failed: %s", e)
        return None

    def _budget_report(self, user_id: Optional[str] = None) -> str:
        uid = user_id or self.default_user
        budgets = self.db.get_budgets(uid, "monthly")
        if not budgets:
            return "No budgets set. Use 'set budget £X for <category> monthly' to create one."

        s, e = current_month_range()
        lines = ["📋 Monthly Budget Report", ""]
        for b in budgets:
            spent = self.db.sum_amount(
                domain="finance", record_type="expense",
                user_id=uid, since=s.isoformat(), until=e.isoformat(),
                category=b["category"],
            )
            remaining = b["amount"] - spent
            pct = (spent / b["amount"] * 100) if b["amount"] > 0 else 0
            status = "⚠️ " if remaining < 0 else "✅ "
            lines.append(
                f"{status}{b['category']:<20} "
                f"Spent: {format_amount(spent):>10}  "
                f"Budget: {format_amount(b['amount']):>10}  "
                f"Remaining: {format_amount(remaining):>10}  ({pct:.0f}%)"
            )
        return "\n".join(lines)

    def _income_summary(self, user_id: Optional[str] = None, space: Optional[str] = None) -> str:
        uid = user_id or self.default_user
        s, e = current_month_range()
        records = self.db.query_records(
            domain="finance", record_type="income",
            user_id=uid, since=s.isoformat(), until=e.isoformat(), limit=100, space=space,
        )
        total = sum(r.get("amount", 0) or 0 for r in records)
        lines = [f"💰 Income this month: {format_amount(total)}", ""]
        for r in records:
            ts = r.get("timestamp", "")[:10]
            lines.append(f"  {ts}  {r.get('description', ''):<35} {format_amount(r.get('amount', 0))}")
        return "\n".join(lines)

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
from datetime import datetime, timedelta
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
    "Marketing": ["marketing", "advertising", "advert", "adverts", "ads", "facebook ads", "fb ads", "google ads", "instagram ads", "tiktok ads", "linkedin ads", "adwords", "sponsored", "campaign", "promotion"],
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

    def _detect_category(self, text: str) -> Optional[str]:
        import re
        for cat, kws in CATEGORY_KEYWORDS.items():
            if cat.lower() in text:
                return cat
            for kw in kws:
                if re.search(r"\b" + re.escape(kw) + r"\b", text):
                    return cat
        return None

    def answer_question(self, question: str, user_id: Optional[str] = None,
                        space: Optional[str] = None) -> str:
        """Answer a natural-language question about the ledger (Financial Memory).

        Handles: how much spent (timeframe), spend on a category, spend at a
        merchant, income, and 'where does my money go'. Deterministic — no LLM."""
        import re
        uid = user_id or self.default_user
        q = question.lower()
        now = datetime.now()

        # Resolve the timeframe mentioned in the question.
        if "today" in q:
            since, until, label = now.replace(hour=0, minute=0, second=0, microsecond=0), now, "today"
        elif "year" in q:
            since, until, label = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0), now, "this year"
        elif "week" in q:
            s, e = current_week_range(now); since, until, label = s, e, "this week"
        elif "last month" in q:
            this_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            until = this_start - timedelta(seconds=1)
            since, label = until.replace(day=1, hour=0, minute=0, second=0, microsecond=0), "last month"
        else:
            s, e = current_month_range(now); since, until, label = s, e, "this month"
        si, ui_ = since.isoformat(), until.isoformat()
        scope = f" in {space}" if space else ""

        # Income.
        if any(w in q for w in ("income", "earn", "earned", "made", "revenue", "received", "paid me")):
            total = self.db.sum_amount("finance", "income", uid, si, ui_, space=space)
            return f"💰 You've received {format_amount(total)}{scope} {label}."

        # "Where does my money go" / biggest area.
        if any(w in q for w in ("biggest", "most", "where", "top")):
            by = self.category_breakdown("month", uid, space=space)
            if not by:
                return f"No spending recorded{scope} yet."
            top, amt = max(by.items(), key=lambda x: x[1])
            return f"🏆 Your biggest area{scope} is {top} — {format_amount(amt)} this month."

        # Spend at a specific merchant ("...at Tesco") — checked before category so
        # 'at Tesco' answers per-merchant rather than per-category.
        m = re.search(r"\bat\s+([a-z][a-z0-9'&\-]{1,20})", q)
        if m and m.group(1) not in ("all", "the", "a"):
            kw = m.group(1)
            recs = self.db.query_records(domain="finance", record_type="expense", user_id=uid,
                                         since=si, until=ui_, limit=5000, space=space)
            total = sum(r.get("amount", 0) or 0 for r in recs if kw in r.get("description", "").lower())
            return f"You've spent {format_amount(total)} at {kw.title()}{scope} {label}."

        # Spend on a specific category.
        cat = self._detect_category(q)
        if cat:
            total = self.db.sum_amount("finance", "expense", uid, si, ui_, category=cat, space=space)
            return f"You've spent {format_amount(total)} on {cat}{scope} {label}."

        # Default: total spend for the timeframe.
        spent = self.db.sum_amount("finance", "expense", uid, si, ui_, space=space)
        income = self.db.sum_amount("finance", "income", uid, si, ui_, space=space)
        out = f"💸 You've spent {format_amount(spent)}{scope} {label}."
        if income:
            out += f"\n💰 Received {format_amount(income)} · net {format_amount(income - spent)}."
        return out

    def spending_insights(self, user_id: Optional[str] = None, space: Optional[str] = None) -> str:
        """Compare this month with last month and surface the notable movements."""
        uid = user_id or self.default_user
        now = datetime.now()

        this_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_end = this_start - timedelta(seconds=1)
        prev_start = prev_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        def _expenses(s, e):
            return self.db.query_records(domain="finance", record_type="expense", user_id=uid,
                                         since=s.isoformat(), until=e.isoformat(), limit=2000, space=space)

        this_exp, prev_exp = _expenses(this_start, now), _expenses(prev_start, prev_end)
        this_total = sum(r.get("amount", 0) or 0 for r in this_exp)
        prev_total = sum(r.get("amount", 0) or 0 for r in prev_exp)

        def _by_cat(rows):
            d: Dict[str, float] = {}
            for r in rows:
                c = r.get("entities", {}).get("category", "Other")
                d[c] = d.get(c, 0) + (r.get("amount", 0) or 0)
            return d

        this_cat, prev_cat = _by_cat(this_exp), _by_cat(prev_exp)

        if not this_exp and not prev_exp:
            return "No spending yet — send me an expense and I'll start spotting trends."

        lines = []
        # Headline: total vs last month.
        if prev_total > 0:
            pct = (this_total - prev_total) / prev_total * 100
            arrow = "🔺" if pct >= 0 else "🔻"
            lines.append(f"💸 Spent {format_amount(this_total)} so far — {arrow} {abs(pct):.0f}% vs last month ({format_amount(prev_total)}).")
        else:
            lines.append(f"💸 Spent {format_amount(this_total)} so far this month.")

        # Top category this month.
        if this_cat:
            top, amt = max(this_cat.items(), key=lambda x: x[1])
            share = (amt / this_total * 100) if this_total else 0
            lines.append(f"🏆 Biggest area: {top} ({format_amount(amt)}, {share:.0f}% of spend).")

        # Biggest mover vs last month.
        movers = []
        for cat in set(this_cat) | set(prev_cat):
            delta = this_cat.get(cat, 0) - prev_cat.get(cat, 0)
            movers.append((cat, delta))
        movers.sort(key=lambda x: -abs(x[1]))
        if movers and abs(movers[0][1]) >= 0.01:
            cat, delta = movers[0]
            if delta > 0:
                lines.append(f"📈 {cat} is up {format_amount(delta)} on last month.")
            else:
                lines.append(f"📉 {cat} is down {format_amount(abs(delta))} on last month.")

        return "\n".join(lines)

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

            # Budget remaining (scoped to this record's Space)
            if memory and amount:
                budget_info = self._budget_remaining(category, amount, memory, space=space)
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

    def set_budget(self, category: str, amount: float, period: str = "monthly",
                   user_id: Optional[str] = None, space: str = "Personal") -> str:
        uid = user_id or self.default_user
        self.db.upsert_budget(uid, category, amount, period, space=space)
        scope = f" [{space}]" if space != "Personal" else ""
        return f"Budget set{scope}: {category} — {format_amount(amount)} per {period}"

    def _budget_remaining(self, category: str, new_spend: float, memory,
                          space: str = "Personal") -> Optional[str]:
        """Return budget remaining string if a budget is set for this category/space."""
        try:
            uid = self.default_user
            budgets = self.db.get_budgets(uid, "monthly", space=space)
            for b in budgets:
                if b["category"].lower() == category.lower():
                    s, e = current_month_range()
                    spent = self.db.sum_amount(
                        domain="finance", record_type="expense",
                        user_id=uid, since=s.isoformat(), until=e.isoformat(),
                        category=category, space=space,
                    )
                    remaining = b["amount"] - spent
                    if remaining < 0:
                        return f"⚠️  Over budget by {format_amount(abs(remaining))} (budget: {format_amount(b['amount'])})"
                    return f"Monthly budget remaining ({category}): {format_amount(remaining)}"
        except Exception as e:
            logger.debug("Budget check failed: %s", e)
        return None

    def _budget_report(self, user_id: Optional[str] = None, space: Optional[str] = None) -> str:
        uid = user_id or self.default_user
        budgets = self.db.get_budgets(uid, "monthly", space=space)
        if not budgets:
            scope = f" for {space}" if space else ""
            return f"No budgets set{scope}. Use /setbudget <category> <amount> to create one."

        s, e = current_month_range()
        scope = f" · {space}" if space else ""
        lines = [f"📋 Monthly Budget Report{scope}", ""]
        for b in budgets:
            spent = self.db.sum_amount(
                domain="finance", record_type="expense",
                user_id=uid, since=s.isoformat(), until=e.isoformat(),
                category=b["category"], space=b.get("space"),
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

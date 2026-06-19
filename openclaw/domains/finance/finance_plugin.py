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

        # Group by currency — different currencies are NEVER summed together
        # (no FX conversion), so each is shown on its own.
        from collections import defaultdict
        exp_by_cur: Dict[str, float] = defaultdict(float)
        inc_by_cur: Dict[str, float] = defaultdict(float)
        cat_by: Dict[tuple, float] = defaultdict(float)  # (category, currency) -> amount
        for r in expenses:
            c, a = r.get("currency", "GBP"), (r.get("amount", 0) or 0)
            exp_by_cur[c] += a
            cat_by[(r.get("entities", {}).get("category", "Other"), c)] += a
        for r in income:
            inc_by_cur[r.get("currency", "GBP")] += (r.get("amount", 0) or 0)

        def _multi(d):  # "₦30.00 · $2.00"
            return " · ".join(format_amount(v, k) for k, v in sorted(d.items(), key=lambda x: -x[1]) if v)

        scope = f" · {space}" if space else ""
        lines = [f"📊 {label} Finance Summary{scope}", ""]
        if any(exp_by_cur.values()):
            lines.append(f"💸 Total Spent:  {_multi(exp_by_cur)}")
        if any(inc_by_cur.values()):
            lines.append(f"💰 Total Income: {_multi(inc_by_cur)}")
        all_curs = {c for c, v in {**exp_by_cur, **inc_by_cur}.items() if v}
        if len(all_curs) == 1 and any(exp_by_cur.values()) and any(inc_by_cur.values()):
            c = next(iter(all_curs))
            lines.append(f"📈 Net:          {format_amount(inc_by_cur[c] - exp_by_cur[c], c)}")

        if cat_by:
            lines.append("")
            lines.append("By category:")
            for (cat, c), amt in sorted(cat_by.items(), key=lambda x: -x[1]):
                lines.append(f"  {cat:<20} {format_amount(amt, c)}")

        if not expenses and not income:
            lines.append("No records found for this period.")

        return "\n".join(lines)

    def _budget_remaining_total(self, uid: str, space: Optional[str]) -> Optional[float]:
        """Sum of (budget − spent) for budgets in the user's primary currency, or
        None if no budgets. Currencies are never mixed (no FX conversion)."""
        budgets = self.db.get_budgets(uid, "monthly", space=space)
        if not budgets:
            return None
        primary = self._user_currency(uid, space)
        budgets = [b for b in budgets if (b.get("currency") or "GBP") == primary]
        if not budgets:
            return None
        s, e = current_month_range()
        rem = 0.0
        for b in budgets:
            spent = self.db.sum_amount("finance", "expense", uid, s.isoformat(), e.isoformat(),
                                       category=b["category"], space=b.get("space"), currency=primary)
            rem += b["amount"] - spent
        return rem

    def daily_digest(self, user_id: Optional[str] = None, space: Optional[str] = None) -> str:
        """Evening recap of today's spending. Real data only."""
        from collections import defaultdict
        uid = user_id or self.default_user
        now = datetime.now()
        since = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        exp = self.db.query_records(domain="finance", record_type="expense", user_id=uid,
                                    since=since, until=now.isoformat(), limit=2000, space=space)
        if not exp:
            return "📊 Today\n\nNo spending logged today — nice one! 🎉"

        by_cur = defaultdict(float)
        biggest = max(exp, key=lambda r: r.get("amount", 0) or 0)
        for r in exp:
            by_cur[r.get("currency", "GBP")] += (r.get("amount", 0) or 0)

        lines = ["📊 Today", ""]
        lines.append("💸 Expenses: " + " · ".join(format_amount(v, k) for k, v in by_cur.items()))
        lines.append(f"🏆 Biggest spend: {biggest.get('description', '')[:30]} "
                     f"{format_amount(biggest.get('amount') or 0, biggest.get('currency', 'GBP'))}")
        rem = self._budget_remaining_total(uid, space)
        if rem is not None:
            lines.append(f"🎯 Budget left this month: {format_amount(rem, self._user_currency(uid, space))}")
        return "\n".join(lines)

    def morning_briefing(self, user_id: Optional[str] = None, space: Optional[str] = None) -> str:
        """Morning recap: yesterday + month-to-date + budget + recurring. No fake balance."""
        from collections import defaultdict
        uid = user_id or self.default_user
        now = datetime.now()
        today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
        y_start = today0 - timedelta(days=1)
        y_exp = self.db.query_records(domain="finance", record_type="expense", user_id=uid,
                                      since=y_start.isoformat(), until=today0.isoformat(),
                                      limit=2000, space=space)
        ms, me = current_month_range(now)
        m_exp = self.db.query_records(domain="finance", record_type="expense", user_id=uid,
                                      since=ms.isoformat(), until=me.isoformat(), limit=5000, space=space)

        def _grp(rows):
            d = defaultdict(float)
            for r in rows:
                d[r.get("currency", "GBP")] += (r.get("amount", 0) or 0)
            return d

        lines = ["☀️ Good morning", ""]
        yg = _grp(y_exp)
        if yg:
            lines.append("Yesterday you spent " + " · ".join(format_amount(v, k) for k, v in yg.items()) + ".")
        else:
            lines.append("Nothing logged yesterday.")
        mg = _grp(m_exp)
        if mg:
            lines.append("This month so far: " + " · ".join(format_amount(v, k) for k, v in mg.items()) + ".")
        rem = self._budget_remaining_total(uid, space)
        if rem is not None:
            lines.append(f"🎯 Budget left this month: {format_amount(rem, self._user_currency(uid, space))}")
        return "\n".join(lines)

    def _user_currency(self, user_id: Optional[str] = None, space: Optional[str] = None) -> str:
        """The user's primary currency = the most common one in their records.
        Aggregates are shown in this currency (no FX conversion is performed)."""
        from collections import Counter
        uid = user_id or self.default_user
        recs = self.db.query_records(domain="finance", user_id=uid, limit=400, space=space)
        counts = Counter(r.get("currency", "GBP") for r in recs if r.get("amount") is not None)
        return counts.most_common(1)[0][0] if counts else "GBP"

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

    def _timeframe_range(self, tf: str):
        """Return (since_iso, until_iso, label) for a timeframe keyword."""
        now = datetime.now()
        if tf == "today":
            s = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return s.isoformat(), now.isoformat(), "today"
        if tf == "year":
            s = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            return s.isoformat(), now.isoformat(), "this year"
        if tf == "week":
            s, e = current_week_range(now)
            return s.isoformat(), e.isoformat(), "this week"
        if tf == "last_month":
            this_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = this_start - timedelta(seconds=1)
            start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return start.isoformat(), end.isoformat(), "last month"
        if tf == "all":
            return None, None, "all time"
        s, e = current_month_range(now)
        return s.isoformat(), e.isoformat(), "this month"

    @staticmethod
    def _detect_timeframe(q: str) -> str:
        if "today" in q:
            return "today"
        if "year" in q:
            return "year"
        if "week" in q:
            return "week"
        if "last month" in q:
            return "last_month"
        return "month"

    def answer_question(self, question: str, user_id: Optional[str] = None,
                        space: Optional[str] = None) -> Optional[str]:
        """Answer a natural-language question about the ledger (Financial Memory).

        Handles common patterns deterministically (no LLM). Returns None when no
        pattern matches, so the caller can fall back to an LLM query planner."""
        import re
        uid = user_id or self.default_user
        q = question.lower()
        si, ui_, label = self._timeframe_range(self._detect_timeframe(q))
        scope = f" in {space}" if space else ""
        cur = self._user_currency(uid, space)

        # Count / "biggest single purchase" → defer to the LLM query planner.
        if any(w in q for w in ("how many", "how often", "number of", " times", "count")):
            return None
        if any(p in q for p in ("biggest purchase", "biggest expense", "largest", "most expensive",
                                "biggest buy", "priciest", "single")):
            return None

        # Income.
        if any(w in q for w in ("income", "earn", "earned", "made", "revenue", "received", "paid me")):
            total = self.db.sum_amount("finance", "income", uid, si, ui_, space=space)
            return f"💰 You've received {format_amount(total, cur)}{scope} {label}."

        # "Where does my money go" / biggest area (category distribution only).
        if any(p in q for p in ("where does my money", "where is my money", "where's my money",
                                "spend the most", "spend most", "biggest category", "biggest area",
                                "money go", "what do i spend most")):
            by = self.category_breakdown("month", uid, space=space)
            if not by:
                return f"No spending recorded{scope} yet."
            top, amt = max(by.items(), key=lambda x: x[1])
            return f"🏆 Your biggest area{scope} is {top} — {format_amount(amt, cur)} this month."

        # Spend at a specific merchant ("...at Tesco") — checked before category so
        # 'at Tesco' answers per-merchant rather than per-category.
        m = re.search(r"\bat\s+([a-z][a-z0-9'&\-]{1,20})", q)
        if m and m.group(1) not in ("all", "the", "a"):
            kw = m.group(1)
            recs = self.db.query_records(domain="finance", record_type="expense", user_id=uid,
                                         since=si, until=ui_, limit=5000, space=space)
            total = sum(r.get("amount", 0) or 0 for r in recs if kw in r.get("description", "").lower())
            return f"You've spent {format_amount(total, cur)} at {kw.title()}{scope} {label}."

        # Spend on a specific category.
        cat = self._detect_category(q)
        if cat:
            total = self.db.sum_amount("finance", "expense", uid, si, ui_, category=cat, space=space)
            return f"You've spent {format_amount(total, cur)} on {cat}{scope} {label}."

        # Default: only answer if it's clearly a spending question, else defer to LLM.
        if any(w in q for w in ("spent", "spend", "cost", "how much", "total", "budget")):
            spent = self.db.sum_amount("finance", "expense", uid, si, ui_, space=space)
            income = self.db.sum_amount("finance", "income", uid, si, ui_, space=space)
            out = f"💸 You've spent {format_amount(spent, cur)}{scope} {label}."
            if income:
                out += f"\n💰 Received {format_amount(income, cur)} · net {format_amount(income - spent, cur)}."
            return out
        return None  # no deterministic match — caller may try the LLM planner

    def execute_query_plan(self, plan: Dict[str, Any], user_id: Optional[str] = None,
                           space: Optional[str] = None) -> str:
        """Execute an LLM-produced query plan deterministically (numbers from the
        ledger, never the model). Supports a constrained metric vocabulary."""
        uid = user_id or self.default_user
        metric = plan.get("metric") or "spend_total"
        si, ui_, label = self._timeframe_range(plan.get("timeframe") or "month")
        category = plan.get("category")
        merchant = (plan.get("merchant") or "").lower() or None
        scope = f" in {space}" if space else ""
        cur = self._user_currency(uid, space)

        def _expenses():
            recs = self.db.query_records(domain="finance", record_type="expense", user_id=uid,
                                         since=si, until=ui_, limit=5000, space=space)
            if category:
                recs = [r for r in recs if r.get("entities", {}).get("category") == category]
            if merchant:
                recs = [r for r in recs if merchant in r.get("description", "").lower()]
            return recs

        if metric == "income_total":
            t = self.db.sum_amount("finance", "income", uid, si, ui_, space=space)
            return f"💰 You've received {format_amount(t, cur)}{scope} {label}."
        if metric == "net":
            inc = self.db.sum_amount("finance", "income", uid, si, ui_, space=space)
            sp = self.db.sum_amount("finance", "expense", uid, si, ui_, space=space)
            return f"📊 Net{scope} {label}: {format_amount(inc - sp, cur)} (in {format_amount(inc, cur)}, out {format_amount(sp, cur)})."
        if metric == "count":
            n = len(_expenses())
            what = f" on {category}" if category else (f" at {merchant.title()}" if merchant else "")
            return f"🧾 {n} transactions{what}{scope} {label}."
        if metric == "largest_expense":
            recs = _expenses()
            if not recs:
                return f"No matching expenses{scope} {label}."
            top = max(recs, key=lambda r: r.get("amount", 0) or 0)
            return (f"💥 Biggest expense{scope} {label}: {format_amount(top.get('amount') or 0, cur)} — "
                    f"{top.get('description', '')[:40]}.")
        if metric == "by_category":
            by = self.category_breakdown(self._detect_timeframe(label.replace("this ", "")), uid, space=space)
            if not by:
                return f"No spending{scope} {label}."
            lines = [f"{c}: {format_amount(a, cur)}" for c, a in by.items()]
            return f"📊 By category{scope} {label}:\n" + "\n".join(lines)

        # spend_total (default)
        recs = _expenses()
        t = sum(r.get("amount", 0) or 0 for r in recs)
        what = f" on {category}" if category else (f" at {merchant.title()}" if merchant else "")
        return f"💸 You've spent {format_amount(t, cur)}{what}{scope} {label}."

    SUBSCRIPTION_KEYWORDS = [
        "netflix", "spotify", "microsoft", "office 365", "prime", "disney", "youtube",
        "icloud", "adobe", "patreon", "audible", "dropbox", "notion", "figma",
        "google one", "gym", "subscription", "membership",
    ]

    def detect_subscriptions(self, user_id: Optional[str] = None, space: Optional[str] = None) -> str:
        """Spot likely recurring charges over the last ~4 months."""
        import re
        from collections import defaultdict
        uid = user_id or self.default_user
        since = (datetime.now() - timedelta(days=125)).isoformat()
        recs = self.db.query_records(domain="finance", record_type="expense", user_id=uid,
                                     since=since, limit=5000, space=space)
        cur = self._user_currency(uid, space)

        def _name(desc: str) -> str:
            words = re.findall(r"[a-z0-9]+", desc.lower())
            words = [w for w in words if w not in ("the", "for", "on", "at", "my", "paid", "bought", "spent")]
            return " ".join(words[:2]) if words else desc.lower()

        groups = defaultdict(list)  # (name, amount) -> [month,...]
        for r in recs:
            amt = round(r.get("amount", 0) or 0, 2)
            if amt <= 0:
                continue
            name = _name(r.get("description", ""))
            month = (r.get("timestamp", "") or "")[:7]
            groups[(name, amt)].append((month, r.get("description", "")))

        detected = []
        for (name, amt), occ in groups.items():
            months = {m for m, _ in occ}
            sample = occ[0][1]
            known = any(k in sample.lower() for k in self.SUBSCRIPTION_KEYWORDS)
            recurring = len(months) >= 2
            if recurring or known:
                detected.append({"name": sample[:30] or name.title(), "amount": amt,
                                 "recurring": recurring})

        if not detected:
            return "No recurring subscriptions detected yet. I spot them once a charge repeats month-to-month."

        detected.sort(key=lambda d: -d["amount"])
        monthly_total = sum(d["amount"] for d in detected if d["recurring"]) or sum(d["amount"] for d in detected)
        lines = []
        for d in detected:
            tag = "" if d["recurring"] else "  (likely)"
            lines.append(f"{d['name']:<24} {format_amount(d['amount'], cur):>9}{tag}")
        lines.append("─" * 34)
        lines.append(f"{'Est. recurring / month':<24} {format_amount(monthly_total, cur):>9}")
        return "\n".join(lines)

    def spending_insights(self, user_id: Optional[str] = None, space: Optional[str] = None) -> str:
        """Compare this month with last month and surface the notable movements."""
        uid = user_id or self.default_user
        cur = self._user_currency(uid, space)
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
            lines.append(f"💸 Spent {format_amount(this_total, cur)} so far — {arrow} {abs(pct):.0f}% vs last month ({format_amount(prev_total, cur)}).")
        else:
            lines.append(f"💸 Spent {format_amount(this_total, cur)} so far this month.")

        # Top category this month.
        if this_cat:
            top, amt = max(this_cat.items(), key=lambda x: x[1])
            share = (amt / this_total * 100) if this_total else 0
            lines.append(f"🏆 Biggest area: {top} ({format_amount(amt, cur)}, {share:.0f}% of spend).")

        # Biggest mover vs last month.
        movers = []
        for cat in set(this_cat) | set(prev_cat):
            delta = this_cat.get(cat, 0) - prev_cat.get(cat, 0)
            movers.append((cat, delta))
        movers.sort(key=lambda x: -abs(x[1]))
        if movers and abs(movers[0][1]) >= 0.01:
            cat, delta = movers[0]
            if delta > 0:
                lines.append(f"📈 {cat} is up {format_amount(delta, cur)} on last month.")
            else:
                lines.append(f"📉 {cat} is down {format_amount(abs(delta), cur)} on last month.")

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

        # Always show which Space this landed in, so the user is never unsure.
        _icons = {"Personal": "🏠", "Business": "💼", "Property": "🏢"}
        lines.append(f"   {_icons.get(space, '🗂')} Space: {space or 'Personal'}")

        # Confidence is only surfaced in developer mode to aid debugging.
        if dev and record.get("confidence") is not None:
            lines.append(f"   Confidence: {record['confidence'] * 100:.0f}%")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Budget management
    # -------------------------------------------------------------------------

    def set_budget(self, category: str, amount: float, period: str = "monthly",
                   user_id: Optional[str] = None, space: str = "Personal",
                   currency: Optional[str] = None) -> str:
        uid = user_id or self.default_user
        cur = currency or self._user_currency(uid, space)
        self.db.upsert_budget(uid, category, amount, period, currency=cur, space=space)
        scope = f" [{space}]" if space != "Personal" else ""
        return f"Budget set{scope}: {category} — {format_amount(amount, cur)} per {period}"

    def _budget_remaining(self, category: str, new_spend: float, memory,
                          space: str = "Personal") -> Optional[str]:
        """Return budget remaining string if a budget is set for this category/space."""
        try:
            uid = self.default_user
            budgets = self.db.get_budgets(uid, "monthly", space=space)
            for b in budgets:
                if b["category"].lower() == category.lower():
                    cur = b.get("currency") or self._user_currency(uid, space)
                    s, e = current_month_range()
                    spent = self.db.sum_amount(
                        domain="finance", record_type="expense",
                        user_id=uid, since=s.isoformat(), until=e.isoformat(),
                        category=category, space=space, currency=cur,
                    )
                    remaining = b["amount"] - spent
                    if remaining < 0:
                        return f"⚠️  Over budget by {format_amount(abs(remaining), cur)} (budget: {format_amount(b['amount'], cur)})"
                    return f"Monthly budget remaining ({category}): {format_amount(remaining, cur)}"
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
        for b in sorted(budgets, key=lambda x: x["category"].lower()):
            cur = b.get("currency") or "GBP"
            # Compare spending only in the budget's own currency (no FX conversion).
            spent = self.db.sum_amount(
                domain="finance", record_type="expense",
                user_id=uid, since=s.isoformat(), until=e.isoformat(),
                category=b["category"], space=b.get("space"), currency=cur,
            )
            remaining = b["amount"] - spent
            pct = (spent / b["amount"] * 100) if b["amount"] > 0 else 0
            # Each budget as a block: name + limit, a bar, then spent / remaining.
            if remaining < 0:
                head = f"⚠️ {b['category']} — {format_amount(b['amount'], cur)}/mo"
                tail = f"{format_amount(spent, cur)} spent · {format_amount(-remaining, cur)} OVER"
            else:
                head = f"🎯 {b['category']} — {format_amount(b['amount'], cur)}/mo"
                tail = f"{format_amount(spent, cur)} spent · {format_amount(remaining, cur)} left"
            lines.append(head)
            lines.append(f"   {self._bar(pct)}  {tail}")
            lines.append("")
        return "\n".join(lines).rstrip()

    @staticmethod
    def _bar(pct: float, width: int = 10) -> str:
        """A 10-char progress bar, e.g. '███░░░░░░░ 30%'. Clamped at 100% (over
        budget is shown in the text)."""
        filled = max(0, min(width, round(pct / 100 * width)))
        return "█" * filled + "░" * (width - filled) + f" {min(pct, 999):.0f}%"

    def _income_summary(self, user_id: Optional[str] = None, space: Optional[str] = None) -> str:
        uid = user_id or self.default_user
        s, e = current_month_range()
        records = self.db.query_records(
            domain="finance", record_type="income",
            user_id=uid, since=s.isoformat(), until=e.isoformat(), limit=100, space=space,
        )
        total = sum(r.get("amount", 0) or 0 for r in records)
        cur = self._user_currency(uid, space)
        lines = [f"💰 Income this month: {format_amount(total, cur)}", ""]
        for r in records:
            ts = r.get("timestamp", "")[:10]
            lines.append(f"  {ts}  {r.get('description', ''):<35} {format_amount(r.get('amount', 0), r.get('currency', cur))}")
        return "\n".join(lines)

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
    "Utilities": ["electric", "electricity", "gas", "water", "internet", "broadband", "wifi", "phone",
                  "bill", "utility", "data", "airtime", "recharge", "mtn", "glo", "airtel", "9mobile", "subscription tv", "dstv", "gotv"],
    "Groceries": ["tesco", "sainsbury", "asda", "waitrose", "lidl", "aldi", "morrisons", "supermarket",
                  "groceries", "grocery", "market",
                  # staple foods / market items (incl. common Naira staples)
                  "rice", "beans", "garri", "gari", "yam", "plantain", "plantains", "bread", "milk",
                  "egg", "eggs", "tomato", "tomatoes", "pepper", "onion", "onions", "sugar", "salt",
                  "flour", "oil", "palm oil", "groundnut oil", "vegetable oil", "fish", "chicken",
                  "meat", "beef", "noodles", "indomie", "spaghetti", "pasta", "semovita", "semo",
                  "garlic", "ginger", "potato", "potatoes", "cassava", "maize", "corn", "milo",
                  "butter", "cereal", "biscuit", "biscuits", "vegetables", "vegetable", "fruit",
                  "fruits", "banana", "apple", "orange", "cabbage", "carrot", "spinach", "ugu",
                  "crayfish", "stockfish", "seasoning", "maggi", "tin tomato"],
    "Shopping": ["amazon", "shop", "store", "clothes", "clothing", "ikea", "argos"],
    "Entertainment": ["cinema", "netflix", "spotify", "game", "ticket", "tickets", "theatre", "concert", "gym", "sport", "sports", "subscription"],
    "Marketing": ["marketing", "advertising", "advert", "adverts", "ads", "facebook ads", "fb ads", "google ads", "instagram ads", "tiktok ads", "linkedin ads", "adwords", "canva", "sponsored", "campaign", "promotion"],
    "Health": ["doctor", "pharmacy", "medication", "dentist", "optician", "hospital", "prescription"],
    "Education": ["course", "book", "tuition", "school", "university", "training", "udemy", "study"],
    "Rent": ["rent", "landlord", "lease"],
    "Salary": ["salary", "wage", "payroll", "pay"],
    "Freelance": ["freelance", "invoice", "client payment", "consulting"],
    "Investment": ["investment", "dividend", "stock", "share", "crypto", "fund"],
}


CATEGORY_ICONS = {
    "Food & Drink": "🍽️", "Groceries": "🛒", "Transport": "🚌", "Utilities": "💡",
    "Shopping": "🛍️", "Entertainment": "🎬", "Marketing": "📣", "Health": "💊",
    "Education": "📚", "Rent": "🏠", "Salary": "💼", "Freelance": "🧾",
    "Investment": "📈", "Income": "💰", "Other": "🔖",
}


# Expense categories the semantic fallback may choose from (income handled elsewhere).
CATEGORIES = ["Food & Drink", "Groceries", "Transport", "Utilities", "Shopping",
              "Entertainment", "Marketing", "Health", "Education", "Rent", "Other"]

CATEGORIZE_PROMPT = (
    "Classify this purchase into exactly one category.\n"
    "Purchase: \"{item}\"\n"
    "Categories: {categories}\n"
    "Reply with ONLY the category name, nothing else."
)


def build_llm_categoriser(llm, db):
    """A semantic fallback: rule-based first, then a cached LLM call for words the
    keyword list can't cover (jollof, shawarma, danfo …). Returns a text->category
    callable. Never raises — degrades to 'Other' on any error."""
    import re

    def _key(text: str) -> str:
        t = re.sub(r"[£$€₦]", " ", (text or "").lower())
        t = re.sub(r"\b\d[\d,]*(?:\.\d+)?\b", " ", t)
        t = re.sub(r"\b(spent|spend|paid|pay|bought|buy|on|for|the|a|an|my|of|at|got|refund|to)\b", " ", t)
        t = re.sub(r"[^a-z ]", " ", t)
        return " ".join(t.split())[:48]

    def _match(raw: str) -> str:
        r = (raw or "").strip().lower()
        for c in CATEGORIES:
            if c.lower() == r:
                return c
        for c in CATEGORIES:
            if c.lower() in r or (r and r in c.lower()):
                return c
        return "Other"

    def categorise(text: str) -> str:
        key = _key(text)
        if not key:
            return "Other"
        hit = db.get_category_cache(key)
        if hit:
            return hit
        try:
            raw = llm.complete(CATEGORIZE_PROMPT.format(item=key, categories=", ".join(CATEGORIES)))
            cat = _match((raw or "").splitlines()[0] if raw else "")
        except Exception:
            return "Other"
        db.set_category_cache(key, cat)
        return cat

    return categorise


def category_icon(category: str) -> str:
    return CATEGORY_ICONS.get(category, "🔖")


def _mini_bar(frac: float, width: int = 5) -> str:
    """A tiny proportion bar like '▰▰▱▱▱' for category share."""
    frac = max(0.0, min(1.0, frac))
    filled = round(frac * width)
    return "▰" * filled + "▱" * (width - filled)


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
        # Optional semantic categoriser (set by the app) for words the keyword
        # list can't cover. None → rule-based only (used in tests).
        self.llm_categorize = None

    def _categorise(self, text: str) -> str:
        """Rule-based first; fall back to the cached LLM categoriser if set."""
        cat = _infer_category(text)
        if cat != "Other":
            return cat
        if self.llm_categorize:
            try:
                return self.llm_categorize(text) or "Other"
            except Exception:
                return "Other"
        return "Other"

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
        import re
        entities = record.setdefault("entities", {})

        # Refunds/returns are a NEGATIVE expense (they offset spend in their
        # category) — never income, whatever the parser guessed.
        text_l = (str(record.get("raw_input", "")) + " " + str(record.get("description", ""))).lower()
        if re.search(r"\b(refund(ed)?|returned|money back|cash\s?back)\b", text_l):
            record["type"] = "expense"
            record["domain"] = "finance"   # a refund is a finance event, not a general note
            amt = record.get("amount")
            if isinstance(amt, (int, float)) and amt > 0:
                record["amount"] = -amt

        # Infer category if not already set
        if not entities.get("category") or entities["category"] == "Other":
            text = record.get("raw_input", "") + " " + record.get("description", "")
            entities["category"] = self._categorise(text)

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

        if not expenses and not income:
            scope = f" · {space}" if space else ""
            return f"📊 <b>{label}</b>{scope}\n\nNo records yet — send me an expense to start. ✨"

        sp_icon = {"Personal": "🏠", "Business": "💼", "Property": "🏢"}.get(space, "🗂") if space else ""
        head = f"{sp_icon} <b>{space}</b> · {label.lower()}" if space else f"<b>{label}</b>"
        lines = [head, ""]
        if any(exp_by_cur.values()):
            lines.append(f"💸 <b>Spent</b>   {_multi(exp_by_cur)}")
        if any(inc_by_cur.values()):
            lines.append(f"💰 <b>Income</b>  {_multi(inc_by_cur)}")
        all_curs = {c for c, v in {**exp_by_cur, **inc_by_cur}.items() if v}
        if len(all_curs) == 1 and any(exp_by_cur.values()) and any(inc_by_cur.values()):
            c = next(iter(all_curs))
            net = inc_by_cur[c] - exp_by_cur[c]
            lines.append(f"{'📈' if net >= 0 else '📉'} <b>Net</b>     {format_amount(net, c)}")

        if cat_by:
            lines.append("\n<b>Where it went</b>")
            for (cat, c), amt in sorted(cat_by.items(), key=lambda x: -x[1]):
                share = amt / exp_by_cur[c] if exp_by_cur.get(c) else 0
                lines.append(f"{category_icon(cat)} {cat} — <b>{format_amount(amt, c)}</b>"
                             f"  <code>{_mini_bar(share)}</code> {share * 100:.0f}%")
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

    def default_currency(self, user_id: Optional[str] = None, space: Optional[str] = None) -> str:
        """The currency a bare amount ("3000") should mean for this user:
        an explicit saved preference, else the one they use most, else GBP.
        Fixes the Naira-user pain of bare numbers defaulting to £."""
        uid = user_id or self.default_user
        pref = self.db.get_currency_pref(uid)
        return pref or self._user_currency(uid, space)

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

    def _sum_by_currency(self, record_type, uid, si, ui_, space,
                         category=None, merchant=None) -> Dict[str, float]:
        """Totals grouped by currency — currencies are NEVER summed together."""
        from collections import defaultdict
        recs = self.db.query_records(domain="finance", record_type=record_type, user_id=uid,
                                     since=si, until=ui_, limit=5000, space=space)
        d: Dict[str, float] = defaultdict(float)
        for r in recs:
            if category and r.get("entities", {}).get("category") != category:
                continue
            if merchant and merchant not in (r.get("description", "") or "").lower():
                continue
            d[r.get("currency", "GBP")] += (r.get("amount") or 0)
        return {k: v for k, v in d.items() if v}

    @staticmethod
    def _fmt_multi(d: Dict[str, float], fallback_cur: str) -> str:
        """'£118.24 · $67.00 · ₦10.00' — or a single zero if empty."""
        if not d:
            return format_amount(0, fallback_cur)
        return " · ".join(format_amount(v, k) for k, v in sorted(d.items(), key=lambda x: -x[1]))

    def _compare_yesterday_today(self, uid: str, space: Optional[str] = None) -> str:
        """Compare yesterday and today by income/spend, grouped per currency."""
        from collections import defaultdict
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)

        def _totals(start, end):
            rows = self.db.query_records(domain="finance", user_id=uid, since=start.isoformat(),
                                         until=end.isoformat(), limit=5000, space=space)
            spent: Dict[str, float] = defaultdict(float)
            income: Dict[str, float] = defaultdict(float)
            cats: Dict[tuple, float] = defaultdict(float)
            for r in rows:
                cur = r.get("currency", "GBP")
                amt = r.get("amount") or 0
                if r.get("type") == "income":
                    income[cur] += amt
                elif r.get("type") == "expense":
                    spent[cur] += amt
                    cats[(r.get("entities", {}).get("category", "Other"), cur)] += amt
            top = max(cats.items(), key=lambda x: x[1], default=None)
            top_text = ""
            if top:
                (cat, cur), amt = top
                top_text = f" · top: {cat} {format_amount(amt, cur)}"
            return dict(spent), dict(income), top_text

        y_spent, y_income, y_top = _totals(yesterday_start, today_start)
        t_spent, t_income, t_top = _totals(today_start, now)
        cur = self._user_currency(uid, space)
        scope = f" · {space}" if space else ""
        return (
            f"📊 Yesterday vs Today{scope}\n"
            f"Yesterday: spent {self._fmt_multi(y_spent, cur)} · income {self._fmt_multi(y_income, cur)}{y_top}\n"
            f"Today: spent {self._fmt_multi(t_spent, cur)} · income {self._fmt_multi(t_income, cur)}{t_top}"
        )

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

        if "compare" in q and "yesterday" in q and "today" in q:
            return self._compare_yesterday_today(uid, space)

        # Count / "biggest single purchase" → defer to the LLM query planner.
        if any(w in q for w in ("how many", "how often", "number of", " times", "count")):
            return None
        if any(p in q for p in ("biggest purchase", "biggest expense", "largest", "most expensive",
                                "biggest buy", "priciest", "single")):
            return None

        # Income.
        if any(w in q for w in ("income", "earn", "earned", "made", "revenue", "received", "paid me")):
            d = self._sum_by_currency("income", uid, si, ui_, space)
            return f"💰 You've received {self._fmt_multi(d, cur)}{scope} {label}."

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
            d = self._sum_by_currency("expense", uid, si, ui_, space, merchant=kw)
            return f"You've spent {self._fmt_multi(d, cur)} at {kw.title()}{scope} {label}."

        # Spend on a specific category.
        cat = self._detect_category(q)
        if cat:
            d = self._sum_by_currency("expense", uid, si, ui_, space, category=cat)
            return f"You've spent {self._fmt_multi(d, cur)} on {cat}{scope} {label}."

        # Default: only answer if it's clearly a spending question, else defer to LLM.
        if any(w in q for w in ("spent", "spend", "cost", "how much", "total", "budget")):
            spent = self._sum_by_currency("expense", uid, si, ui_, space)
            income = self._sum_by_currency("income", uid, si, ui_, space)
            out = f"💸 You've spent {self._fmt_multi(spent, cur)}{scope} {label}."
            if income:
                out += f"\n💰 Received {self._fmt_multi(income, cur)}."
                # Net only when everything is in one shared currency (no FX).
                curs = set(spent) | set(income)
                if len(curs) == 1:
                    c = next(iter(curs))
                    out += f" · net {format_amount(income.get(c, 0) - spent.get(c, 0), c)}."
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
            d = self._sum_by_currency("income", uid, si, ui_, space)
            return f"💰 You've received {self._fmt_multi(d, cur)}{scope} {label}."
        if metric == "net":
            inc = self._sum_by_currency("income", uid, si, ui_, space)
            sp = self._sum_by_currency("expense", uid, si, ui_, space)
            curs = set(inc) | set(sp)
            if len(curs) <= 1:
                c = next(iter(curs), cur)
                return (f"📊 Net{scope} {label}: {format_amount(inc.get(c, 0) - sp.get(c, 0), c)} "
                        f"(in {self._fmt_multi(inc, cur)}, out {self._fmt_multi(sp, cur)}).")
            return f"📊{scope} {label}: in {self._fmt_multi(inc, cur)} · out {self._fmt_multi(sp, cur)} (currencies kept separate)."
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
        from collections import defaultdict
        d: Dict[str, float] = defaultdict(float)
        for r in _expenses():
            d[r.get("currency", "GBP")] += (r.get("amount") or 0)
        what = f" on {category}" if category else (f" at {merchant.title()}" if merchant else "")
        return f"💸 You've spent {self._fmt_multi(dict(d), cur)}{what}{scope} {label}."

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

        import html
        detected.sort(key=lambda d: -d["amount"])
        monthly_total = sum(d["amount"] for d in detected if d["recurring"]) or sum(d["amount"] for d in detected)
        lines = []
        for d in detected:
            tag = "" if d["recurring"] else "  <i>(likely)</i>"
            lines.append(f"🔁 <b>{html.escape(d['name'])}</b> — <b>{format_amount(d['amount'], cur)}</b>{tag}")
        lines.append("")
        lines.append(f"≈ <b>{format_amount(monthly_total, cur)}</b> / month recurring")
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

    def monthly_recap(self, user_id: Optional[str] = None, space: Optional[str] = None,
                      month_offset: int = 0) -> Dict[str, Any]:
        """Gather a shareable monthly recap (the 'Wrapped' card). Numbers are in
        the user's primary currency; no balances, nothing sensitive by default.
        month_offset=-1 recaps last month (used by the 1st-of-month auto-send)."""
        from collections import defaultdict
        now = datetime.now()
        if month_offset < 0:
            anchor = now.replace(day=1) - timedelta(days=1)   # last day of previous month
        else:
            anchor = now
        uid = user_id or self.default_user
        s, e = current_month_range(anchor)
        cur = self.default_currency(uid, space)
        exp = [r for r in self.db.query_records(domain="finance", record_type="expense", user_id=uid,
                                                since=s.isoformat(), until=e.isoformat(), limit=5000, space=space)
               if (r.get("currency") or "GBP") == cur]
        inc = [r for r in self.db.query_records(domain="finance", record_type="income", user_id=uid,
                                                since=s.isoformat(), until=e.isoformat(), limit=5000, space=space)
               if (r.get("currency") or "GBP") == cur]

        by_cat: Dict[str, float] = defaultdict(float)
        for r in exp:
            by_cat[r.get("entities", {}).get("category", "Other")] += (r.get("amount") or 0)
        spent = sum(r.get("amount") or 0 for r in exp)
        income = sum(r.get("amount") or 0 for r in inc)
        biggest = max(exp, key=lambda r: r.get("amount") or 0, default=None)
        top = max(by_cat.items(), key=lambda x: x[1], default=(None, 0))

        # Badges — small brag tokens.
        badges = []
        streak = self._logging_streak(uid, space)
        if streak >= 2:
            badges.append(f"🔥 {streak}-day logging streak")
        budgets = self.db.get_budgets(uid, "monthly", space=space)
        if budgets:
            under = sum(1 for b in budgets
                        if self.db.sum_amount("finance", "expense", uid, s.isoformat(), e.isoformat(),
                                              category=b["category"], space=b.get("space"),
                                              currency=b.get("currency") or cur) <= b["amount"])
            badges.append(f"🎯 Under budget in {under}/{len(budgets)}")
        if len(exp) + len(inc):
            badges.append(f"🧾 {len(exp) + len(inc)} logged")

        return {
            "label": anchor.strftime("%B %Y"), "space": space or "Personal", "currency": cur,
            "spent": spent, "income": income, "count": len(exp) + len(inc),
            "by_category": dict(sorted(by_cat.items(), key=lambda x: -x[1])),
            "top_category": top, "biggest": biggest, "badges": badges,
            "empty": not exp and not inc,
        }

    def _logging_streak(self, user_id: str, space: Optional[str] = None) -> int:
        """Consecutive days up to today with at least one entry."""
        rows = self.db.query_records(domain="finance", user_id=user_id, limit=2000, space=space)
        days = {(r.get("timestamp", "") or "")[:10] for r in rows}
        from datetime import timedelta
        d = datetime.now().date()
        streak = 0
        while d.isoformat() in days:
            streak += 1
            d -= timedelta(days=1)
        return streak

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

        if rtype == "expense" and (amount or 0) < 0:
            # A refund/credit — present it as money back that reduces the category,
            # not as a new expense, so it never looks like a stray entry.
            back = format_amount(-amount, currency)
            tail = f" on {category}" if category else ""
            lines.append(f"↩️ Recorded refund: {back} back{tail} (it reduces your spend).")
            lines.append(f"   ID: {self._transaction_id(record)}")

        elif rtype == "expense":
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

        import html
        s, e = current_month_range()
        lines = []
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
            name = html.escape(b["category"])
            icon = "⚠️" if remaining < 0 else category_icon(b["category"])
            standing = (f"<b>{format_amount(-remaining, cur)} over</b>" if remaining < 0
                        else f"<b>{format_amount(remaining, cur)} left</b>")
            lines.append(f"{icon} <b>{name}</b> · {format_amount(b['amount'], cur)}/mo")
            lines.append(f"<code>{self._bar(pct)}</code>  {format_amount(spent, cur)} spent · {standing}")
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
        import html
        total = sum(r.get("amount", 0) or 0 for r in records)
        cur = self._user_currency(uid, space)
        if not records:
            return "💰 No income logged this month yet.\nTell me when money comes in: <i>got salary 3200</i>."
        lines = [f"💰 <b>{format_amount(total, cur)}</b> in this month", ""]
        for r in records:
            ts = r.get("timestamp", "") or ""
            try:
                day = datetime.fromisoformat(ts).strftime("%d %b").lstrip("0")
            except (ValueError, TypeError):
                day = ts[:10]
            desc = html.escape((r.get("description", "") or "")[:30])
            lines.append(f"💰 <i>{day}</i>  <b>{format_amount(r.get('amount', 0), r.get('currency', cur))}</b> — {desc}")
        return "\n".join(lines)

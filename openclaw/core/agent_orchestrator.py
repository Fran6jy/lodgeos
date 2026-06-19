"""
Agent Orchestrator — the main entry point for processing user messages.

Flow:
  Input → IntentParser → SchemaValidator → Router → Plugin → Storage → Response

This is the single public interface all integrations (CLI, Telegram, API) call.
"""

import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, Optional

# Prefixes that look like "Word:" but are NOT Budget Spaces.
_SPACE_PREFIX_STOPLIST = {
    "note", "reminder", "todo", "fyi", "ps", "re", "btw", "update", "fix",
    "eg", "ie", "etc", "warning", "error", "http", "https", "nb", "memo",
}

from openclaw.core.intent_parser import IntentParser
from openclaw.core.correction_detector import CorrectionDetector
from openclaw.core.document_parser import DocumentParser
from openclaw.core.schema_validator import SchemaValidator, ValidationError
from openclaw.core.router import Router
from openclaw.core.memory_store import MemoryStore
from openclaw.utils.currency_normalizer import format_amount

logger = logging.getLogger(__name__)


class ProcessingResult:
    """Encapsulates the outcome of processing a single message."""

    def __init__(
        self,
        success: bool,
        record: Optional[Dict[str, Any]],
        response: str,
        domain: str,
        elapsed_ms: float,
        error: Optional[str] = None,
        pending: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.record = record
        self.response = response
        self.domain = domain
        self.elapsed_ms = elapsed_ms
        self.error = error
        # When set, an interactive choice is required (e.g. ambiguous correction).
        # Shape: {"action": "UPDATE_EXISTING"|"DELETE_EXISTING", "updates": {...},
        #         "candidates": [{"id","description","amount","currency"}]}
        self.pending = pending

    def __repr__(self):
        return f"ProcessingResult(success={self.success}, domain={self.domain}, elapsed={self.elapsed_ms:.0f}ms)"


class AgentOrchestrator:
    """Main orchestration engine. All integrations go through here."""

    def __init__(self, llm_client, router: Router, memory: Optional[MemoryStore] = None,
                 dev: bool = False, vision_client=None):
        self.llm = llm_client
        self.parser = IntentParser(llm_client)
        self.corrector = CorrectionDetector(llm_client)
        self.doc_parser = DocumentParser(vision_client) if vision_client else None
        self._shopping = None
        self.validator = SchemaValidator()
        self.router = router
        self.memory = memory or MemoryStore()
        self.dev = dev

    def _resolve_space(self, message: str, user_id: str):
        """Return (space, cleaned_message). A 'Space: ...' prefix overrides the
        user's active space for this one entry — but only when the prefix matches a
        KNOWN space (defaults + ones the user created via /space). This avoids
        hijacking ordinary colons like 'Lunch: £12'. Otherwise the active space applies."""
        db = self._storage()
        active = db.get_active_space(user_id) if db else "Personal"
        if db is None:
            return active, message
        m = re.match(r"^\s*([A-Za-z][A-Za-z0-9 &'\-]{0,28}?):\s+(.+)$", message, re.DOTALL)
        if m:
            prefix = m.group(1).strip()
            known = {s.lower(): s for s in db.list_spaces(user_id)}
            if prefix.lower() in known and prefix.lower() not in _SPACE_PREFIX_STOPLIST:
                return known[prefix.lower()], m.group(2).strip()
        return active, message

    @property
    def shopping(self):
        if self._shopping is None:
            from openclaw.core.shopping import ShoppingManager
            fin = self.router._registry.get("finance")
            self._shopping = ShoppingManager(
                self._storage(),
                lambda u, s: fin._user_currency(u, s) if fin else "GBP",
            )
        return self._shopping

    def _handle_shopping_signal(self, signal, user_id, space, start):
        kind = signal[0]
        if kind == "reply":
            return self._result(True, None, signal[1], start)
        if kind == "buy":
            _, list_name, items = signal
            return self._buy_list(list_name, items, user_id, space, start)
        if kind == "budget":
            _, list_name, items = signal
            return self._list_to_budget(list_name, items, user_id, space, start)
        return self._result(False, None, "Couldn't handle that list action.", start)

    @staticmethod
    def _group_items_by_category(items):
        """Group shopping items into {(category, currency): {total, items}}.

        Uses an item's explicit category tag when present, else infers from the
        name; market items with no signal default to Groceries."""
        from collections import defaultdict
        from openclaw.domains.finance.finance_plugin import _infer_category
        groups = defaultdict(lambda: {"total": 0.0, "items": []})
        for it in items:
            cat = it.get("category") or _infer_category(it.get("item", ""))
            if cat == "Other":
                cat = "Groceries"
            cur = it.get("currency", "GBP")
            g = groups[(cat, cur)]
            g["total"] += it.get("amount") or 0
            g["items"].append(it.get("item", ""))
        return groups

    def _list_to_budget(self, list_name, items, user_id, space, start):
        """Turn a price-check list into monthly category budgets (keeps the list)."""
        groups = self._group_items_by_category(items)
        for (cat, cur), g in groups.items():
            self._storage().upsert_budget(user_id, cat, round(g["total"], 2), "monthly",
                                          currency=cur, space=space or "Personal")
        breakdown = " · ".join(
            f"{cat} {format_amount(g['total'], cur)}" for (cat, cur), g in groups.items()
        )
        resp = (f"🎯 Set monthly budgets from “{list_name}”: {breakdown}.\n"
                f"The list is still here — say “bought {list_name}” once you've shopped.")
        return self._result(True, None, resp, start, domain="finance")

    def _buy_list(self, list_name, items, user_id, space, start):
        """Convert a shopping list into expense record(s) — one per (category, currency).

        Each item is auto-categorised by name (market items default to Groceries),
        so a mixed trip lands in the right categories instead of all under Groceries."""
        groups = self._group_items_by_category(items)

        records = []
        for (cat, cur), g in groups.items():
            names = ", ".join(g["items"])
            rec = {
                "domain": "finance", "type": "expense", "amount": round(g["total"], 2), "currency": cur,
                "description": f"{list_name}: {names}"[:120],
                "entities": {"category": cat}, "raw_input": f"bought {list_name}",
                "confidence": 0.9, "user_id": user_id, "space": space,
                "timestamp": datetime.now().isoformat(),
            }
            plugin, domain = self.router.route(rec)
            rec["domain"] = domain
            rec = plugin.transform(rec)
            rec["entities"]["category"] = cat  # keep our deliberate categorisation
            plugin.store(rec)
            self.memory.add(rec)
            records.append(rec)
        self._storage().clear_shopping_list(user_id, space, list_name)

        breakdown = " · ".join(
            f"{cat} {format_amount(g['total'], cur)}" for (cat, cur), g in groups.items()
        )
        resp = f"✅ Bought “{list_name}” — logged {breakdown}. List cleared."
        return self._result(bool(records), records[0] if records else None, resp, start, domain="finance")

    def _storage(self):
        """Return a storage adapter from any registered plugin that has one."""
        for plugin in self.router._registry.values():
            db = getattr(plugin, "db", None)
            if db is not None:
                return db
        return None

    # Money-like tokens: currency-attached amounts, thousands-separated numbers,
    # or decimal money. Used to decide if a message holds multiple transactions.
    _MONEY_RE = re.compile(
        r"[£$€₦¥₹]\s*\d[\d,]*(?:\.\d+)?"
        r"|\d[\d,]*(?:\.\d+)?\s*[£$€₦¥₹]"
        r"|\d[\d,]*(?:\.\d+)?\s*(?:naira|pounds?|dollars?|euros?|cedis?|shillings?|gbp|usd|ngn|eur|ghs|kes)"
        r"|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b"
        r"|\b\d+\.\d{2}\b",
        re.IGNORECASE,
    )

    def _route_budget(self, message: str, user_id: str, space: str, start: float):
        """Single owner of every budget-related message. Classifies into one intent
        in priority order and dispatches to the relevant executor.

        Returns:
          {"result": ProcessingResult}      — handled, this is the reply
          {"forced_category", "message"}    — log an expense against a budget; the
                                              caller continues recording with this category
          None                              — not a budget message, continue normally
        """
        low = message.lower()
        has_budget = "budget" in low
        sm = self.shopping
        db = self._storage()
        active = db.get_active_list(user_id) if db else None
        amount = sm.parse_budget(low)
        mentions_cat = sm.mentions_category(low)
        budget_for = bool(re.search(r"\bbudget\s+(?:for|on)\b", low))
        spend_verb = bool(re.search(r"\b(spent|spend|paid|bought|buy|withdrew|sent|spending|cost me)\b", low))
        explicit_set = bool(re.search(r"\b(set|setup|create|make)\b[^.?]*\bbudget\b", low))
        conversion = bool(re.search(r"\b(convert|turn|use|save|make)\b", low))
        delete_verb = bool(re.search(r"\b(delete|void|cancel|remove|undo|drop|scrap|clear)\b", low))
        query_verb = bool(re.search(r"\b(show|view|see|list|what|whats|how much|check|my budgets?)\b", low))
        rename_verb = bool(re.search(r"\b(rename|relabel)\b", low))
        all_word = bool(re.search(r"\b(all|every|everything)\b", low))

        # 0a0) Rename a budget ("rename the food budget to groceries").
        if has_budget and rename_verb:
            mm = re.search(r"\brename\s+(?:the\s+|my\s+)?(.+?)\s+budget\s+to\s+(.+)$", message, re.IGNORECASE)
            if mm and db:
                old = self._budget_name_ref(f"{mm.group(1)} budget", user_id, space) or mm.group(1).strip().title()
                new = self._normalize_budget_name(mm.group(2))
                if db.rename_budget(user_id, old, new, "monthly", space):
                    return {"result": self._result(True, None, f"✏️ Renamed “{old}” budget to “{new}”.",
                                                   start, domain="finance")}
                return {"result": self._result(False, None, f"I couldn't find a “{old}” budget to rename.", start)}
            return {"result": self._result(False, None,
                    "Rename like this: “rename the Food budget to Groceries”.", start)}

        # 0a1) Delete ALL budgets — needs confirmation.
        if has_budget and delete_verb and all_word:
            n = len(db.get_budgets(user_id, "monthly", space=space)) if db else 0
            if n == 0:
                return {"result": self._result(False, None, f"No budgets to delete in {space}.", start)}
            return {"result": self._result(
                False, None,
                f"⚠️ This will delete ALL {n} budget(s) in your {space} space. Are you sure?",
                start, pending={"action": "CLEAR_BUDGETS", "space": space, "count": n, "candidates": []})}

        # 0a2) Delete/void one budget ("delete the food budget").
        if has_budget and delete_verb:
            cat = self._budget_name_ref(message, user_id, space)
            if cat and db and db.delete_budget(user_id, cat, "monthly", space):
                return {"result": self._result(True, None, f"🗑️ Deleted the {cat} budget.", start, domain="finance")}
            return {"result": self._result(False, None,
                    "Which budget should I delete? e.g. “delete the Food budget”.", start)}

        # 0b) Show budgets ("show me my budgets", "what are my budgets").
        if has_budget and query_verb and amount is None and not explicit_set and not conversion:
            plugin = self.router._registry.get("finance")
            if plugin is not None:
                return {"result": self._result(True, None, plugin._budget_report(user_id, space=space),
                                               start, domain="finance")}

        # 1) Convert a price-check list into category budgets (no amount, no category).
        if has_budget and conversion and amount is None and not budget_for and not mentions_cat:
            name = active or sm.name_in(message, user_id, space)
            if name and db:
                items = sm.items_for_signal(user_id, space, name)
                if not items:
                    return {"result": self._result(False, None, f"Your “{name}” list is empty.", start)}
                return {"result": self._handle_shopping_signal(("budget", name, items), user_id, space, start)}

        # 2) Set a finance budget — names a category or "budget for", with an amount.
        #    A spending verb means "log against", not "set", unless it says set/create.
        if has_budget and (mentions_cat or budget_for or explicit_set) and not (spend_verb and not explicit_set):
            res = self._try_budget_intent(message, user_id, space, start)
            if res is not None:
                return {"result": res}

        # 3) Trip budget for the open list ("budget 20000", "set the budget to 20000").
        if has_budget and active and amount is not None and not mentions_cat and not budget_for \
                and not spend_verb \
                and re.search(r"(?:^|\b(?:set|the|my|a|our|trip|list|shopping|market)\s+)budget\b", low):
            reply = sm.set_trip_budget(user_id, space, amount)
            if reply is not None:
                return {"result": self._result(True, None, reply, start, domain="finance")}

        # 4) Log an expense against a named budget — annotate and continue recording.
        cat, cleaned = self._explicit_category(message, user_id, space)
        if cat:
            return {"forced_category": cat, "message": cleaned}
        return None

    def _try_budget_intent(self, message: str, user_id: str, space: str, start: float):
        """Set a budget from plain language ("set budget for tea 50"). Returns a
        ProcessingResult if it's a budget command, else None (so it isn't recorded
        as an expense). Asks for the amount if none was given."""
        low = message.lower()
        if "budget" not in low:
            return None
        # A spending verb means "log an expense (against a budget)", not "set a
        # budget" — unless it explicitly says set/create a budget.
        if re.search(r"\b(spent|spend|paid|bought|buy|withdrew|sent|cost me|spending)\b", low) \
                and not re.search(r"\b(set|setup|create|make)\b[^.?]*\bbudget\b", low):
            return None
        # Must look like *setting* a budget, not a query (questions are filtered upstream).
        if not (re.search(r"\bset\b", low) or re.search(r"budget\b[^.?]*\bfor\b", low)
                or re.search(r"\bbudget\b[^.?]*[£$€₦]?\d", low)):
            return None

        from openclaw.utils.currency_normalizer import extract_amount_and_currency
        amount, currency = extract_amount_and_currency(message, "GBP")

        # Category = the message stripped of amounts and budget keywords.
        cat_src = re.sub(r"[£$€₦]?\s*\d[\d,]*(?:\.\d+)?", " ", message)
        cat_src = re.sub(
            r"\b(set|setup|create|a|an|my|the|please|monthly|weekly|month|week|budget|budgets|"
            r"for|of|to|is|are|on|at|limit|cap|naira|pounds?|dollars?|euros?|gbp|usd|ngn|eur|"
            r"amount|amounts|not|known|yet)\b", " ", cat_src, flags=re.IGNORECASE)
        cat_src = re.sub(r"[^a-zA-Z &]", " ", cat_src)
        category = " ".join(w for w in cat_src.split() if len(w) >= 2).strip().title()
        if not category:
            return None
        # Snap to a standard category when recognised ("food" → "Food & Drink",
        # "fuel" → "Transport") so budgets reconcile with auto-categorised spending.
        # Unrecognised names ("Tea", "Per Diems") stay as custom categories.
        from openclaw.domains.finance.finance_plugin import _infer_category
        canonical = _infer_category(category)
        if canonical != "Other":
            category = canonical

        plugin = self.router._registry.get("finance")
        if plugin is None:
            return None
        if amount is None:
            return self._result(
                False, None,
                f"🎯 Sure — what monthly limit for {category}? e.g. “set {category} budget to 50”.",
                start)
        plugin.set_budget(category, amount, "monthly", user_id=user_id, space=space, currency=currency)
        scope = f" · {space}" if space and space != "Personal" else ""
        return self._result(
            True, None, f"🎯 Budget set: {category} — {format_amount(amount, currency)} per month{scope}", start)

    def _budget_name_ref(self, message: str, user_id: str, space: str):
        """Find which existing budget a message refers to ("delete the food budget"
        → "Food & Drink"). Returns the budget category name, or None."""
        db = self._storage()
        names = sorted((b["category"] for b in (db.get_budgets(user_id, "monthly", space=space) if db else [])),
                       key=len, reverse=True)
        if not names:
            return None
        low = message.lower()
        # The phrase before "budget", minus leading verbs/articles.
        m = re.search(r"(.+?)\s+budget\b", low)
        cand = m.group(1) if m else low
        cand = re.sub(r"\b(delete|void|cancel|remove|undo|drop|scrap|clear|the|my|a|an|please|all)\b",
                      " ", cand)
        cwords = set(re.findall(r"[a-z]+", cand))
        for n in names:                                   # exact name appears
            if re.search(r"\b" + re.escape(n.lower()) + r"\b", low):
                return n
        for n in names:                                   # word-subset ("food" → "Food & Drink")
            nwords = set(re.findall(r"[a-z]+", n.lower()))
            if cwords and nwords and (cwords <= nwords or nwords <= cwords):
                return n
        from openclaw.domains.finance.finance_plugin import _infer_category
        canonical = _infer_category(cand)                 # "fuel" → "Transport"
        if canonical != "Other":
            for n in names:
                if n.lower() == canonical.lower():
                    return n
        return None

    def _explicit_category(self, message: str, user_id: str, space: str):
        """Detect an explicit category/budget reference and return
        (category_or_None, message_with_that_clause_removed).

        Recognises "... from/for/under the <name> budget" and bare mentions of an
        existing budget category, so "spent 10£ ... from the Yi Shaun Costs budget"
        is logged against that budget."""
        from openclaw.domains.finance.finance_plugin import _infer_category
        db = self._storage()
        names = sorted((b["category"] for b in (db.get_budgets(user_id, "monthly", space=space) if db else [])),
                       key=len, reverse=True)

        def _match(raw: str) -> Optional[str]:
            raw = raw.strip()
            rl = raw.lower()
            for n in names:                       # an existing budget, exact
                if n.lower() == rl:
                    return n
            rwords = set(re.findall(r"[a-z]+", rl))
            for n in names:                       # ... or a word-subset ("karate" → "Karate Costs")
                nwords = set(re.findall(r"[a-z]+", n.lower()))
                if rwords and (rwords <= nwords or nwords <= rwords):
                    return n
            canonical = _infer_category(raw)
            if canonical != "Other":
                return canonical
            cleaned = " ".join(w for w in re.sub(r"[^a-zA-Z &]", " ", raw).split() if len(w) >= 2)
            return cleaned.title() or None

        m = re.search(r"\b(?:from|for|under|against|out of|in|to|towards?)\s+(?:the\s+|my\s+)?(.+?)\s+budget\b",
                      message, re.IGNORECASE)
        if m:
            return _match(m.group(1)), (message[:m.start()] + " " + message[m.end():])
        for n in names:                            # bare existing-budget name
            if re.search(r"\b" + re.escape(n) + r"\b", message, re.IGNORECASE):
                return n, message
        return None, message

    _NUM_ONES = {
        "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
        "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
        "seventeen": 17, "eighteen": 18, "nineteen": 19,
    }
    _NUM_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
                 "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}

    @classmethod
    def _normalize_number_words(cls, text: str) -> str:
        """Turn simple spoken numbers into digits: "eight ten" → "8 10",
        "three fifty" → "3 50", "twenty five" → "25". Leaves hundred/thousand
        alone so "eight hundred ten" is NOT read as a pence amount."""
        words = text.split()
        out, i = [], 0
        while i < len(words):
            w = words[i].lower().strip(".,!?")
            nxt = words[i + 1].lower().strip(".,!?") if i + 1 < len(words) else ""
            if w in cls._NUM_TENS and nxt in cls._NUM_ONES and 1 <= cls._NUM_ONES[nxt] <= 9:
                out.append(str(cls._NUM_TENS[w] + cls._NUM_ONES[nxt])); i += 2; continue
            if w in cls._NUM_TENS:
                out.append(str(cls._NUM_TENS[w])); i += 1; continue
            if w in cls._NUM_ONES:
                out.append(str(cls._NUM_ONES[w])); i += 1; continue
            out.append(words[i]); i += 1
        return " ".join(out)

    def _ambiguous_amount(self, message: str, default_currency: str, space: str,
                          forced_category):
        """Detect a spoken "<whole> <pence>" amount ("eight ten" → 8.10 / 810) and
        return a pending AMOUNT_CONFIRM payload, or None. Conservative: needs a
        money context and a 2-digit second part, so it rarely false-fires."""
        from openclaw.utils.currency_normalizer import SYMBOL_MAP, WORD_MAP
        norm = self._normalize_number_words(message)
        # An integer pair "<A> <B>" with B two digits (10-99) and no decimals around.
        m = re.search(r"(?<![.\d])([£$€₦])?\s*(\d{1,4})\s+(\d{2})(?![.\d])", norm)
        if not m:
            return None
        # Require a money context so unrelated number pairs don't trigger.
        sym = m.group(1)
        cur_word = re.search(r"\b(naira|pounds?|dollars?|euros?|gbp|usd|ngn|eur)\b", message, re.IGNORECASE)
        spend = re.search(r"\b(spent|spend|paid|pay|bought|buy|cost|costs?|got|received|earned|made|salary)\b",
                          message, re.IGNORECASE)
        if not (sym or cur_word or spend):
            return None
        a, b = int(m.group(2)), int(m.group(3))
        decimal = float(f"{a}.{b:02d}")
        whole = float(f"{a}{b:02d}")
        if decimal == whole:
            return None
        currency = (SYMBOL_MAP.get(sym or "") or WORD_MAP.get((cur_word.group(1).lower() if cur_word else ""))
                    or default_currency)
        rtype = "income" if re.search(r"\b(got|received|earned|made|salary|income)\b", message, re.IGNORECASE) else "expense"
        # Description = what's left after stripping numbers, currency and verbs.
        d = re.sub(r"[£$€₦]", " ", norm)
        d = re.sub(r"\b\d+\b", " ", d)
        d = re.sub(r"\b(spent|spend|paid|pay|bought|buy|cost|costs?|got|received|earned|made|salary|income|"
                   r"on|for|the|a|an|i|me|my|of|to|at|naira|pounds?|dollars?|euros?|gbp|usd|ngn|eur)\b",
                   " ", d, flags=re.IGNORECASE)
        description = " ".join(d.split()).strip() or "entry"
        return {
            "action": "AMOUNT_CONFIRM", "candidates": [
                {"amount": decimal, "currency": currency},
                {"amount": whole, "currency": currency},
            ],
            "description": description, "type": rtype, "space": space,
            "category": forced_category, "user_id": None,  # filled in by the bot layer
        }

    def record_amount_choice(self, payload: dict, index: int, user_id: str):
        """Store the expense/income the user picked from an AMOUNT_CONFIRM prompt."""
        start = time.perf_counter()
        c = payload["candidates"][index]
        rec = {
            "domain": "finance", "type": payload.get("type", "expense"),
            "amount": c["amount"], "currency": c["currency"],
            "description": payload.get("description", "entry"),
            "entities": {"category": payload["category"]} if payload.get("category") else {},
            "raw_input": payload.get("description", ""), "confidence": 0.95,
            "user_id": user_id, "space": payload.get("space", "Personal"),
            "timestamp": datetime.now().isoformat(),
        }
        plugin, domain = self.router.route(rec)
        rec["domain"] = domain
        rec = plugin.transform(rec)
        if payload.get("category"):
            rec["entities"]["category"] = payload["category"]
        plugin.store(rec)
        self.memory.add(rec)
        try:
            response = plugin.build_response(rec, self.memory, dev=self.dev)
        except TypeError:
            response = plugin.build_response(rec, self.memory)
        return self._result(True, rec, response, start, domain="finance")

    def _is_multi_item(self, message: str) -> bool:
        """True if the message looks like several transactions (a list, or 2+ amounts)."""
        lines = [l for l in message.splitlines() if re.search(r"\d", l)]
        if "\n" in message and len(lines) >= 2:
            return True
        return len(self._MONEY_RE.findall(message)) >= 2

    def _extract_line_items_rule(self, message: str, default_currency: str) -> list:
        """Deterministically split "10£ on rice and 20£ on food" into transactions.

        Handles the common "<amount> on/for <thing>" pattern repeated with
        and/comma separators. Returns [] when it doesn't clearly match, so the
        LLM splitter can take over."""
        from openclaw.utils.currency_normalizer import SYMBOL_MAP, WORD_MAP
        cur_word = r"(?:naira|pounds?|dollars?|euros?|gbp|usd|ngn|eur)"
        # Amount with a leading OR trailing symbol/word: "£10", "10£", "10 naira".
        pat = re.compile(
            rf"([£$€₦])?\s*(\d[\d,]*(?:\.\d+)?)\s*([£$€₦])?\s*({cur_word})?\s+(?:on|for)\s+"
            rf"(.+?)(?=\s+(?:and|,|;|plus)\s+[£$€₦]?\s*\d|\s*[,;]|$)",
            re.IGNORECASE,
        )
        income = bool(re.search(r"\b(received|earned|got paid|income|salary|made)\b", message, re.IGNORECASE))
        items = []
        for m in pat.finditer(message):
            amt = float(m.group(2).replace(",", ""))
            cur = (SYMBOL_MAP.get(m.group(1) or "") or SYMBOL_MAP.get(m.group(3) or "")
                   or WORD_MAP.get((m.group(4) or "").lower()) or default_currency)
            desc = re.sub(r"\bthe\b", " ", m.group(5), flags=re.IGNORECASE).strip(" .")
            items.append({
                "amount": amt, "currency": cur,
                "description": desc[:80] or "entry",
                "type": "income" if income else "expense",
            })
        if len(items) >= 2:
            return items

        # Fallback: bare amounts joined by plus/and/comma ("10£ plus 20£"), where
        # the rest is only connector/verb words — split one record per amount.
        leftover = re.sub(r"[£$€₦]?\s*\d[\d,]*(?:\.\d+)?\s*[£$€₦]?\s*" + cur_word + r"?",
                          " ", message, flags=re.IGNORECASE)
        leftover_words = {w for w in re.findall(r"[a-z]+", leftover.lower())}
        connectors = {"spent", "spend", "paid", "plus", "and", "also", "then", "another",
                      "i", "a", "of", "the", "my", "in", "to", "on", "for", "budget"}
        if leftover_words <= connectors:
            amt_pat = re.compile(rf"([£$€₦])?\s*(\d[\d,]*(?:\.\d+)?)\s*([£$€₦])?\s*({cur_word})?", re.IGNORECASE)
            bare = []
            for m in amt_pat.finditer(message):
                if not m.group(2):
                    continue
                cur = (SYMBOL_MAP.get(m.group(1) or "") or SYMBOL_MAP.get(m.group(3) or "")
                       or WORD_MAP.get((m.group(4) or "").lower()) or default_currency)
                bare.append({"amount": float(m.group(2).replace(",", "")), "currency": cur,
                             "description": "entry", "type": "income" if income else "expense"})
            if len(bare) >= 2:
                return bare
        return []

    def _extract_line_items(self, message: str, default_currency: str) -> list:
        """Use the LLM to split one message into individual transactions."""
        from openclaw.llm.prompt_templates import LINE_ITEMS_PROMPT
        from openclaw.core.intent_parser import _has_explicit_currency
        from openclaw.utils.currency_normalizer import (
            extract_amount_and_currency, SYMBOL_MAP, WORD_MAP)

        msg_cur = default_currency
        if _has_explicit_currency(message):
            _, msg_cur = extract_amount_and_currency(message, default_currency)

        def _norm_cur(c):
            if not c:
                return None
            return SYMBOL_MAP.get(c) or WORD_MAP.get(str(c).lower()) or str(c).upper()

        try:
            raw = self.llm.complete(LINE_ITEMS_PROMPT.format(message=message))
            data = self._parse_plan(raw)
        except Exception as e:
            logger.warning("Line-item extraction failed: %s", e)
            return []
        if isinstance(data, dict):
            data = data.get("items") or data.get("transactions") or [data]
        items = []
        for d in (data or []):
            try:
                amt = float(d.get("amount"))
            except (TypeError, ValueError):
                continue
            items.append({
                "amount": amt,
                "currency": _norm_cur(d.get("currency")) or msg_cur,
                "description": (d.get("description") or "entry")[:80],
                "type": d.get("type") if d.get("type") in ("expense", "income") else "expense",
            })
        return items

    def _record_items(self, items: list, user_id: str, space: str, start: float,
                      forced_category: Optional[str] = None) -> ProcessingResult:
        """Store each extracted item as its own record; return a grouped receipt.

        When forced_category is set (e.g. "from the Yi Shaun Costs budget"), every
        item is assigned that category instead of one inferred from its name."""
        from collections import defaultdict
        records = []
        for it in items:
            desc = it["description"]
            if desc in ("", "entry") and forced_category:
                desc = forced_category
            rec = {
                "domain": "finance", "type": it["type"], "amount": it["amount"],
                "currency": it["currency"], "description": desc,
                "entities": {"category": forced_category} if forced_category else {},
                "raw_input": desc, "confidence": 0.8,
                "user_id": user_id, "space": space, "timestamp": datetime.now().isoformat(),
            }
            plugin, domain = self.router.route(rec)
            rec["domain"] = domain
            rec = plugin.transform(rec)
            if forced_category:
                rec["entities"]["category"] = forced_category
            plugin.store(rec)
            self.memory.add(rec)
            records.append(rec)

        lines_out = [f"🧾 Recorded {len(records)} entries:"]
        totals = defaultdict(float)
        for rec in records:
            amt, cur = rec.get("amount") or 0, rec.get("currency", "GBP")
            if rec.get("type") == "expense":
                totals[cur] += amt
            cat = rec.get("entities", {}).get("category", "")
            lines_out.append(f"✅ {format_amount(amt, cur)} — {rec.get('description', '')[:38]} ({cat})")
        if any(totals.values()):
            lines_out.append("💸 Total spent: " + " · ".join(format_amount(v, k) for k, v in totals.items() if v))
        if space and space != "Personal":
            lines_out.append(f"🗂 Space: {space}")
        elapsed = (time.perf_counter() - start) * 1000
        return ProcessingResult(bool(records), records[0] if records else None,
                                "\n".join(lines_out), "finance", elapsed)

    def process(self, message: str, user_id: str = "default",
                default_currency: str = "GBP") -> ProcessingResult:
        """
        Process a natural language message end-to-end.

        Returns a ProcessingResult with the stored record and human response.
        """
        start = time.perf_counter()

        try:
            # Step -1: Resolve the Budget Space (prefix override or active space).
            space, message = self._resolve_space(message, user_id)

            # Step 0a: Bulk void ("void/delete all entries") — deterministic, and
            # always requires explicit confirmation before touching anything.
            if re.search(r"\b(void|delete|remove|clear|wipe)\b.{0,20}\b(all|every)\b.{0,20}\b(entr|record|transaction|expense)", message, re.IGNORECASE):
                db = self._storage()
                count = len(db.query_records(domain="finance", user_id=user_id, limit=10000, space=space)) if db else 0
                if count == 0:
                    return self._result(False, None, f"Nothing to void — no active entries in {space}.", start)
                return self._result(
                    False, None,
                    f"⚠️ This will void ALL {count} entries in your {space} space "
                    f"(kept for audit, excluded from totals). Are you sure?",
                    start,
                    pending={"action": "VOID_ALL", "space": space, "count": count, "candidates": []},
                )

            # Step 0a0: Greeting / smalltalk — reply with a hint, don't record it.
            if re.fullmatch(r"(hi|hello|hey+|hiya|yo|sup|howdy|greetings|good\s*(morning|afternoon|"
                            r"evening|day)|thanks?|thank\s*you|ta|cheers|ok|okay|cool|nice|great|"
                            r"good|👍|🙏)[\s.!?]*", message.strip(), re.IGNORECASE):
                return self._result(
                    False, None,
                    "👋 Hi! Send me an expense like “spent £4 on coffee”, start a shopping list, "
                    "or set a budget. Tap Menu for options.",
                    start)

            # Step 0a1: Budget router — the single owner of every "budget" message
            # (set / convert-list / trip / log-against). Returns a terminal result,
            # or annotates (forced_category + cleaned message) and lets us continue.
            forced_category = None
            budget = self._route_budget(message, user_id, space, start)
            if budget is not None:
                if "result" in budget:
                    return budget["result"]
                forced_category = budget.get("forced_category")
                message = budget.get("message", message)

            # Step 0a2: Shopping / price lists ("start a chai list", "bought chai",
            # or bare items while a list is open). Checked before recording so list
            # items aren't logged as expenses.
            shop_signal = self.shopping.handle(message, user_id, space)
            if shop_signal is not None:
                return self._handle_shopping_signal(shop_signal, user_id, space, start)

            # Step 0b: Multiple transactions in one message (a list, or a spoken
            # paragraph with several amounts) → record each separately.
            if self._is_multi_item(message):
                items = []
                # For a single-line "10£ on rice and 20£ on food", split deterministically
                # (reliable, offline) — but only if it captures every amount. Otherwise
                # defer to the LLM splitter, which handles messy multi-line paragraphs.
                if "\n" not in message:
                    rule = self._extract_line_items_rule(message, default_currency)
                    if len(rule) == len(self._MONEY_RE.findall(message)):
                        items = rule
                if len(items) < 2:
                    items = self._extract_line_items(message, default_currency)
                if len(items) >= 2:
                    return self._record_items(items, user_id, space, start, forced_category=forced_category)

            # Step 0a4: Ambiguous spoken amount ("eight ten" → £8.10 or £810?).
            # Don't guess about money — offer a one-tap choice.
            amb = self._ambiguous_amount(message, default_currency, space, forced_category)
            if amb is not None:
                labels = " or ".join(format_amount(c["amount"], c["currency"]) for c in amb["candidates"])
                return self._result(False, None, f"🤔 Did you mean {labels}? Tap one 👇",
                                    start, pending=amb)

            # Step 0: Is this a correction to an existing entry, or a new one?
            classification = self.corrector.classify(message, self.memory.recent(domain="finance"))
            intent = classification.get("intent", "RECORD_NEW")
            if intent in ("UPDATE_EXISTING", "DELETE_EXISTING"):
                return self._handle_correction(intent, classification, user_id, message, start)

            # Step 1: Parse intent and extract entities
            record = self.parser.parse(message, default_currency=default_currency)
            record["user_id"] = user_id
            record["processed_at"] = datetime.now().isoformat()

            # Step 2: Validate schema
            try:
                self.validator.validate_or_raise(record)
            except ValidationError as e:
                logger.warning("Validation errors (non-fatal): %s", e.errors)
                # Non-fatal: log and continue with what we have

            # Step 3: Route to domain plugin
            plugin, domain = self.router.route(record)
            record["domain"] = domain

            # Step 4: Plugin transform + store (tag with the resolved Space)
            record["space"] = space
            record = plugin.transform(record)
            if forced_category:
                record.setdefault("entities", {})["category"] = forced_category
            plugin.store(record)

            # Step 5: Update session memory
            self.memory.add(record)

            # Step 6: Build human response
            try:
                response = plugin.build_response(record, self.memory, dev=self.dev)
            except TypeError:
                # Plugins that don't accept a dev flag still work.
                response = plugin.build_response(record, self.memory)

            elapsed = (time.perf_counter() - start) * 1000
            logger.info("Processed in %.1fms | domain=%s | type=%s", elapsed, domain, record.get("type"))

            return ProcessingResult(
                success=True,
                record=record,
                response=response,
                domain=domain,
                elapsed_ms=elapsed,
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.exception("Orchestrator error processing: %r", message)
            return ProcessingResult(
                success=False,
                record=None,
                response=f"Sorry, I couldn't process that. Error: {e}",
                domain="unknown",
                elapsed_ms=elapsed,
                error=str(e),
            )

    def process_document(self, image_b64: str, mime: str = "image/jpeg", user_id: str = "default") -> ProcessingResult:
        """Parse an image (receipt/invoice/payslip/etc.) into a stored record."""
        start = time.perf_counter()
        if self.doc_parser is None:
            return self._result(False, None, "Image parsing isn't configured (no vision model).", start)
        try:
            record = self.doc_parser.parse(image_b64, mime)
            record["user_id"] = user_id
            db = self._storage()
            record["space"] = db.get_active_space(user_id) if db else "Personal"
            record["processed_at"] = datetime.now().isoformat()
            record.setdefault("timestamp", datetime.now().isoformat())

            try:
                self.validator.validate_or_raise(record)
            except ValidationError as e:
                logger.warning("Document validation (non-fatal): %s", e.errors)

            plugin, domain = self.router.route(record)
            record["domain"] = domain
            record = plugin.transform(record)
            plugin.store(record)
            self.memory.add(record)

            try:
                response = plugin.build_response(record, self.memory, dev=self.dev)
            except TypeError:
                response = plugin.build_response(record, self.memory)
            response = "🧾 " + response

            elapsed = (time.perf_counter() - start) * 1000
            logger.info("Document processed in %.1fms | type=%s | amount=%s", elapsed, record.get("type"), record.get("amount"))
            return ProcessingResult(True, record, response, domain, elapsed)
        except Exception as e:
            logger.exception("Document processing error")
            return self._result(False, None, f"Couldn't read that document: {e}", start)

    def _handle_correction(self, intent, classification, user_id, message, start):
        """Apply an UPDATE/DELETE correction. Confirms only when ambiguous."""
        db = self._storage()
        if db is None:
            return self._result(False, None, "Corrections aren't available — no storage configured.", start)

        crit = classification.get("target_search_criteria", {}) or {}
        approx = crit.get("approximate_old_amount")
        keyword = crit.get("old_description_keyword")

        # Guard against hallucinated keywords: only trust a search keyword that
        # actually appears in the user's message. Otherwise a noisy model can
        # silently target an unrelated record (e.g. matching "5pounds"/"cream"
        # from a stale entry when the user only said "delete the £5 one").
        if keyword and keyword.lower() not in message.lower():
            logger.info("Dropping unverified correction keyword %r (not in message)", keyword)
            keyword = None

        candidates = db.search_records(
            user_id=user_id,
            approx_amount=approx,
            keyword=keyword,
            limit=5,
        )

        if not candidates:
            hint = []
            if approx is not None:
                hint.append(f"~{format_amount(approx)}")
            if keyword:
                hint.append(f"'{keyword}'")
            detail = (" matching " + " ".join(hint)) if hint else ""
            return self._result(False, None, f"🔍 I couldn't find an entry{detail} to correct.", start)

        updates = classification.get("updates", {}) or {}
        clean = {k: v for k, v in updates.items() if v is not None and k in ("amount", "description", "category", "currency")}
        # If a correction changes the description but not the category, re-infer it
        # from the new text (e.g. "I meant £30 on facebook ads" → Marketing).
        if clean.get("description") and not clean.get("category"):
            from openclaw.domains.finance.finance_plugin import _infer_category
            inferred = _infer_category(clean["description"])
            if inferred != "Other":
                clean["category"] = inferred
        if intent == "UPDATE_EXISTING" and not clean:
            return self._result(False, None, "I detected a correction but no new value to apply.", start)

        # Confirm only when ambiguous: more than one record matches → ask interactively.
        if len(candidates) > 1:
            pending = {
                "action": intent,
                "updates": clean,
                "candidates": [
                    {
                        "id": r.get("id"),
                        "description": r.get("description", ""),
                        "amount": r.get("amount"),
                        "currency": r.get("currency", "GBP"),
                    }
                    for r in candidates
                ],
            }
            verb = "void" if intent == "DELETE_EXISTING" else "update"
            return self._result(
                False, None,
                f"🔎 I found multiple matching entries — which one should I {verb}?",
                start, pending=pending,
            )

        return self._apply_correction_to(candidates[0], intent, clean, start)

    def apply_void_all(self, user_id: str, space: Optional[str] = None):
        """Confirmed bulk void: soft-void every active record in the space."""
        start = time.perf_counter()
        db = self._storage()
        if db is None:
            return self._result(False, None, "Storage unavailable.", start)
        n = db.void_all_records(user_id, space=space)
        return self._result(True, None,
                            f"🗑️ Voided {n} entries in {space or 'all spaces'}. "
                            f"They're excluded from totals but kept for audit.", start)

    def apply_clear_budgets(self, user_id: str, space: Optional[str] = None):
        """Confirmed: delete every budget in the space."""
        start = time.perf_counter()
        db = self._storage()
        if db is None:
            return self._result(False, None, "Storage unavailable.", start)
        n = db.delete_all_budgets(user_id, "monthly", space or "Personal")
        return self._result(True, None, f"🗑️ Deleted {n} budget(s) in {space or 'Personal'}.",
                            start, domain="finance")

    def _normalize_budget_name(self, raw: str) -> str:
        """Clean a typed budget name and snap it to a standard category when known."""
        from openclaw.domains.finance.finance_plugin import _infer_category
        name = " ".join(w for w in re.sub(r"[^a-zA-Z &]", " ", raw).split() if len(w) >= 2).strip().title()
        canon = _infer_category(name)
        return canon if canon != "Other" else (name or "Other")

    def apply_correction(self, record_id, action, updates, user_id="default"):
        """Apply a correction to a specific record (used by interactive selection)."""
        start = time.perf_counter()
        db = self._storage()
        target = db.get_record(record_id) if db else None
        if not target or target.get("voided"):
            return self._result(False, None, "That entry is no longer available.", start)
        return self._apply_correction_to(target, action, updates or {}, start)

    def _apply_correction_to(self, target, action, clean, start):
        """Perform the void/update on a single resolved record."""
        db = self._storage()
        target_id = target.get("id")
        old_amt = format_amount(target.get("amount") or 0, target.get("currency", "GBP"))

        if action == "DELETE_EXISTING":
            ok = db.void_record(target_id)
            msg = (f"🗑️ Voided: {target.get('description', '')} ({old_amt}). "
                   f"It's excluded from totals but kept for audit." if ok
                   else "Couldn't void that entry (already voided?).")
            return self._result(ok, target, msg, start, domain="finance")

        updated = db.update_record(target_id, clean)
        if not updated:
            return self._result(False, target, "Couldn't apply that correction.", start)

        changes = []
        if "amount" in clean:
            changes.append(f"amount {old_amt} → {format_amount(updated.get('amount') or 0, updated.get('currency', 'GBP'))}")
        if "category" in clean:
            changes.append(f"category → {updated.get('entities', {}).get('category')}")
        if "description" in clean:
            changes.append(f"description → \"{updated.get('description')}\"")
        if "currency" in clean:
            changes.append(f"currency → {updated.get('currency')}")
        return self._result(True, updated, "✏️ Updated: " + "; ".join(changes), start, domain="finance")

    def _result(self, success, record, response, start, domain="finance", pending=None):
        elapsed = (time.perf_counter() - start) * 1000
        return ProcessingResult(
            success=success, record=record, response=response,
            domain=domain, elapsed_ms=elapsed,
            error=None if success else response, pending=pending,
        )

    def answer(self, question: str, user_id: str = "default", space: Optional[str] = None) -> str:
        """Answer a NL question: deterministic patterns first, LLM query-planner fallback."""
        plugin = self.router._registry.get("finance")
        if plugin is None:
            return "I can't answer that right now."

        det = plugin.answer_question(question, user_id, space=space)
        if det is not None:
            return det

        # Fallback: ask the LLM to translate the question into a query plan, then
        # execute it deterministically so the numbers come from the ledger.
        try:
            from openclaw.llm.prompt_templates import QUERY_PLAN_PROMPT
            raw = self.llm.complete(QUERY_PLAN_PROMPT.format(question=question))
            plan = self._parse_plan(raw)
            if plan.get("metric"):
                return plugin.execute_query_plan(plan, user_id, space=space)
        except Exception as e:
            logger.warning("Query planner failed: %s", e)
        return ("I can answer things like \"how much have I spent this month\", "
                "\"how much at Tesco\", \"what's my biggest expense\", or \"net this year\".")

    @staticmethod
    def _parse_plan(raw: str) -> Dict[str, Any]:
        text = (raw or "").strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
        return {}

    def query(self, request: str, domain: Optional[str] = None) -> str:
        """
        Handle a query (not a new record) — e.g. "show me this week's expenses".
        Routes to the relevant plugin's query handler.
        """
        if domain:
            plugin = self.router._registry.get(domain)
            if plugin:
                return plugin.query(request)
        # Try all plugins until one handles it
        for plugin in self.router._registry.values():
            try:
                result = plugin.query(request)
                if result:
                    return result
            except Exception:
                continue
        return "No data found for that query."

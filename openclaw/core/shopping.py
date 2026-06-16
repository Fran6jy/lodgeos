"""
Shopping / price-list manager — natural language, deterministic.

Lets a user plan a market trip in plain language:

    "start a chai list: ginger 500, milk 1200, cardamom 800"
    "add cardamom 800 to chai"
    "ginger is actually 700"        (update a price)
    "show chai"                      (view the running total)
    "bought chai"                    (convert the list into one expense)

A short-lived "active list" lets follow-up item messages drop into the open list
without repeating its name. Returns a signal the orchestrator turns into a reply
or an expense; returns None when the message isn't a list interaction.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from openclaw.utils.currency_normalizer import SYMBOL_MAP, WORD_MAP, format_amount

# A signal back to the orchestrator: ("reply", text) | ("buy", list_name, items)
Signal = Tuple[str, ...]

# Canonical categories an item can be tagged with, e.g. "phone charger 5000 [shopping]".
_CATEGORY_TAGS = {
    "groceries": "Groceries", "grocery": "Groceries",
    "food": "Food & Drink", "drink": "Food & Drink", "drinks": "Food & Drink", "food & drink": "Food & Drink",
    "transport": "Transport", "fare": "Transport", "fuel": "Transport", "transportation": "Transport",
    "utilities": "Utilities", "utility": "Utilities", "bill": "Utilities", "bills": "Utilities",
    "shopping": "Shopping", "shop": "Shopping",
    "entertainment": "Entertainment", "fun": "Entertainment",
    "marketing": "Marketing", "ads": "Marketing",
    "health": "Health", "medical": "Health", "medicine": "Health",
    "education": "Education", "school": "Education",
    "rent": "Rent",
    "other": "Other",
}

_STOP_WORDS = {
    "add", "to", "the", "a", "an", "my", "list", "for", "of", "on", "at", "each",
    "cost", "costs", "is", "was", "now", "about", "around", "approximately", "price",
    "priced", "and", "plus", "with", "some", "buy", "get", "got", "need", "want",
}


class ShoppingManager:
    def __init__(self, db, currency_fn):
        self.db = db
        self.currency_fn = currency_fn  # (user_id, space) -> currency code

    # -- public -------------------------------------------------------------

    def handle(self, message: str, user_id: str, space: str) -> Optional[Signal]:
        low = message.lower().strip()
        active = self.db.get_active_list(user_id)

        # Exit / finish the open list.
        if active and re.fullmatch(r"(done|finish(ed)?|that'?s all|close( list)?|exit( list)?|stop|no more)\.?", low):
            self.db.set_active_list(user_id, None)
            return ("reply", self._render(user_id, space, active, header=f"✅ Saved your “{active}” list."))

        # Show lists.
        if re.search(r"\bmy lists\b", low) or re.fullmatch(r"lists?\.?", low):
            return ("reply", self._render_all(user_id, space))
        if re.search(r"\b(show|view|see|what'?s on|open)\b.*\blist\b", low):
            name = self._name_in(message, user_id, space) or active
            if name:
                return ("reply", self._render(user_id, space, name))
            return ("reply", self._render_all(user_id, space))

        # Buy → convert to an expense.
        if re.search(r"\b(bought|buy|purchased|paid for|done shopping|finished shopping)\b", low) and (
            re.search(r"\blist\b", low) or active or self._name_in(message, user_id, space)
        ):
            name = self._name_in(message, user_id, space) or active
            if not name:
                return ("reply", "Which list did you buy? e.g. “bought chai”.")
            items = self.db.get_shopping_items(user_id, space, name)
            if not items:
                return ("reply", f"Your “{name}” list is empty.")
            self.db.set_active_list(user_id, None)
            return ("buy", name, self.items_for_signal(user_id, space, name))

        # NB: "budget" intents (set / convert-list / trip / log-against) are owned by
        # the orchestrator's single budget router, which runs before this handler.

        # Remove a single item: "remove milk from the chai list".
        if re.search(r"\b(remove|drop|delete|take\s+off|take\s+out)\b", low):
            name = self._name_in(message, user_id, space) or active
            if name:
                body = re.sub(r"\b(remove|drop|delete|take\s+off|take\s+out|from|off|out\s+of)\b",
                              " ", message, flags=re.IGNORECASE)
                kw = self._clean_name(self._strip_list_ref(body, name))
                if kw:
                    self.db.set_active_list(user_id, name)
                    removed = self.db.delete_shopping_item(user_id, space, name, kw)
                    if removed:
                        return ("reply", self._render(user_id, space, name, header=f"➖ Removed {removed}"))
                    return ("reply", f"I couldn’t find “{kw}” on “{name}”.")

        # Clear / delete a list.
        if re.search(r"\b(clear|empty|delete|cancel|scrap|remove)\b.*\blist\b", low):
            name = self._name_in(message, user_id, space) or active
            if name:
                n = self.db.clear_shopping_list(user_id, space, name)
                if active and active.lower() == name.lower():
                    self.db.set_active_list(user_id, None)
                return ("reply", f"🗑️ Cleared “{name}” ({n} items).")
            return ("reply", "Which list should I clear?")

        # Create a new list.
        m = re.search(r"\b(start|create|new|make|begin)\b.{0,20}?(?:\b(shopping|price|market)\b\s*)?\blist\b", low)
        m2 = re.search(r"\b(start|create|new|make|begin)\s+(?:a |the |my )?([a-z][a-z ]*?)\s+(?:shopping |price )?list\b", low)
        if m or m2:
            name = (m2.group(2).strip().title() if m2 else self._name_in(message, user_id, space)) or "Shopping"
            name = self._clean_name(name)
            self.db.set_active_list(user_id, name)
            budget = self._parse_budget(low)
            if budget is not None:
                self.db.set_active_list_budget(user_id, budget)
            # any items mentioned inline (after ':' / 'with' / the word list)
            inline = message.split(":", 1)[1] if ":" in message else re.split(r"\bwith\b|\blist\b", message, flags=re.I)[-1]
            # don't let a trailing "budget 20000" become an item
            inline = re.sub(r"\bbudget\b.*$", "", inline, flags=re.IGNORECASE)
            items = self._parse_items(inline, self.currency_fn(user_id, space))
            for it in items:
                self.db.add_shopping_item(user_id, space, name, it["item"], it["amount"], it["currency"], it["quantity"], it.get("category"))
            head = f"🛒 Started “{name}”." + ("" if items else " Add items like “ginger 500, milk 1200”, then say “done”.")
            return ("reply", self._render(user_id, space, name, header=head))

        # Explicit add: "add ginger 500, milk 1200 to chai"
        if re.search(r"\badd\b.*\bto\b.*\blist\b", low) or (re.search(r"\badd\b", low) and self._name_in(message, user_id, space)):
            name = self._name_in(message, user_id, space) or active
            if not name:
                return ("reply", "Add to which list? e.g. “add ginger 500 to chai list”.")
            self.db.set_active_list(user_id, name)
            return self._add(message, user_id, space, name)

        # (Trip budget for the open list is handled by the orchestrator's budget router.)

        # Adjust an item's quantity: "make ginger 2", "add 2 more ginger", "1 less milk".
        if active:
            edit = self._try_qty_edit(low, user_id, space, active)
            if edit:
                return edit

        # Update a price: "ginger is actually 700"
        if active:
            um = re.search(r"\b([a-z][a-z ]+?)\s+(?:is|was|costs?|now|actually|came to)\b[^0-9]*?([£$€₦]?\d[\d,]*(?:\.\d+)?)", low)
            if um:
                kw = self._clean_name(um.group(1))
                amt = float(re.sub(r"[£$€₦,]", "", um.group(2)))
                hit = self.db.update_shopping_item(user_id, space, active, kw, amt)
                cur = self.currency_fn(user_id, space)
                if hit:
                    return ("reply", self._render(user_id, space, active, header=f"✏️ {hit} → {format_amount(amt, cur)}"))

        # Mode add: a bare item list while a list is open.
        if active and self._looks_like_items(low):
            return self._add(message, user_id, space, active)

        return None

    # -- public helpers used by the orchestrator's budget router ------------

    def items_for_signal(self, user_id: str, space: str, name: str) -> List[Dict[str, Any]]:
        """List items as buy/convert signal entries (amount = unit × quantity)."""
        items = self.db.get_shopping_items(user_id, space, name)
        return [{"item": i["item"], "amount": (i["amount"] or 0) * (i.get("quantity") or 1),
                 "currency": i.get("currency", "GBP"), "category": i.get("category")}
                for i in items]

    def set_trip_budget(self, user_id: str, space: str, amount: float) -> Optional[str]:
        """Set the open list's trip budget; return a rendered reply, or None if no
        list is open."""
        active = self.db.get_active_list(user_id)
        if not active:
            return None
        self.db.set_active_list_budget(user_id, amount)
        cur = self.currency_fn(user_id, space)
        return self._render(user_id, space, active,
                            header=f"🎯 Budget for “{active}” set to {format_amount(amount, cur)}")

    def parse_budget(self, low: str) -> Optional[float]:
        return self._parse_budget(low)

    def mentions_category(self, low: str) -> bool:
        return self._mentions_category(low)

    def name_in(self, message: str, user_id: str, space: str) -> Optional[str]:
        return self._name_in(message, user_id, space)

    # -- helpers ------------------------------------------------------------

    def _add(self, message: str, user_id: str, space: str, name: str) -> Signal:
        # Drop a leading verb ("add 2 tomatoes 200") so it can't shadow the quantity.
        body = re.sub(r"^\s*(?:add|get|buy|need|want|grab|put|include)\s+", " ", message, flags=re.IGNORECASE)
        items = self._parse_items(self._strip_list_ref(body, name), self.currency_fn(user_id, space))
        if not items:
            return ("reply", "I didn’t catch an item + price. Try “ginger 500, milk 1200”.")
        for it in items:
            self.db.add_shopping_item(user_id, space, name, it["item"], it["amount"], it["currency"], it["quantity"])
        added = ", ".join(self._item_label(i) for i in items)
        return ("reply", self._render(user_id, space, name, header=f"➕ Added {added}"))

    @staticmethod
    def _mentions_category(low: str) -> bool:
        """True if the text names a spend category — used to tell a finance category
        budget ("set budget for food 100") from a list trip budget ("budget 20000")."""
        return any(re.search(r"\b" + re.escape(tok) + r"\b", low) for tok in _CATEGORY_TAGS)

    @staticmethod
    def _parse_budget(low: str) -> Optional[float]:
        m = re.search(r"\bbudget\b[^0-9£$€₦]{0,10}([£$€₦]?\d[\d,]*(?:\.\d+)?)", low)
        if not m:
            m = re.search(r"([£$€₦]?\d[\d,]*(?:\.\d+)?)\s*budget\b", low)
        if not m:
            return None
        return float(re.sub(r"[£$€₦,]", "", m.group(1)))

    def _try_qty_edit(self, low: str, user_id: str, space: str, name: str) -> Optional[Signal]:
        # A budget command ("set budget for food 100") is never a quantity edit.
        if "budget" in low:
            return None
        # increment: "add 2 more ginger" / "2 more ginger"
        m = re.search(r"\b(?:add\s+)?(\d+)\s+more\s+([a-z][a-z ]*)", low)
        if m:
            return self._apply_qty(user_id, space, name, m.group(2), delta=float(m.group(1)))
        # "another ginger" / "one more ginger"
        m = re.search(r"\b(?:another|one\s+more)\s+([a-z][a-z ]*)", low)
        if m:
            return self._apply_qty(user_id, space, name, m.group(1), delta=1)
        # decrement: "2 less milk" / "one fewer milk"
        m = re.search(r"\b(\d+)\s+(?:less|fewer)\s+([a-z][a-z ]*)", low)
        if m:
            return self._apply_qty(user_id, space, name, m.group(2), delta=-float(m.group(1)))
        m = re.search(r"\b(?:one|1)\s+(?:less|fewer)\s+([a-z][a-z ]*)", low)
        if m:
            return self._apply_qty(user_id, space, name, m.group(1), delta=-1)
        # set: "make/set/change ginger to 2" (also "... ginger 2")
        m = re.search(r"\b(?:make|set|change)\s+([a-z][a-z ]*?)\s+(?:to\s+|qty\s+|quantity\s+|=\s*)?(\d+)\b", low)
        if m:
            return self._apply_qty(user_id, space, name, m.group(1), qty=float(m.group(2)))
        return None

    def _apply_qty(self, user_id: str, space: str, name: str, kw_raw: str,
                   qty: Optional[float] = None, delta: Optional[float] = None) -> Optional[Signal]:
        kw = self._clean_name(kw_raw)
        if not kw:
            return None
        res = self.db.update_shopping_quantity(user_id, space, name, kw, qty=qty, delta=delta)
        if not res:
            return ("reply", f"I couldn’t find “{kw}” on “{name}”.")
        item, new_qty = res
        return ("reply", self._render(user_id, space, name, header=f"🔢 {item} × {self._qty_str(new_qty)}"))

    @staticmethod
    def _strip_list_ref(message: str, name: str) -> str:
        """Remove the "to/for the <list> list" clause so the list name doesn't
        leak into a parsed item (e.g. "add star anise to the chai list 100")."""
        words = re.escape(name).replace(r"\ ", r"\s+")
        # "to/for/in/on (the|my) <name> (list)"
        out = re.sub(rf"\b(?:to|for|in|on)\s+(?:the\s+|my\s+)?{words}(?:\s+list)?\b",
                     " ", message, flags=re.IGNORECASE)
        # any leftover bare list-name mention
        out = re.sub(rf"\b{words}\b", " ", out, flags=re.IGNORECASE)
        return out

    @staticmethod
    def _qty_str(qty: float) -> str:
        return str(int(qty)) if float(qty).is_integer() else f"{qty:g}"

    def _item_label(self, it: Dict[str, Any]) -> str:
        qty = it.get("quantity") or 1
        line = (it["amount"] or 0) * qty
        if qty != 1:
            return f"{self._qty_str(qty)}× {it['item']} {format_amount(line, it['currency'])}"
        return f"{it['item']} {format_amount(it['amount'] or 0, it['currency'])}"

    def _looks_like_items(self, low: str) -> bool:
        # Has a number, and no expense/question/command verbs.
        if not re.search(r"\d", low):
            return False
        if re.search(r"\b(spent|paid|received|earned|salary|how much|how many|what|delete|void|budget|switch)\b", low):
            return False
        return True

    def _parse_items(self, text: str, default_cur: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for part in re.split(r"[,;]|\band\b|\bplus\b", text, flags=re.IGNORECASE):
            category, part = self._extract_category(part)
            qty, part = self._extract_qty(part)
            m = re.search(r"([£$€₦])?\s*(\d[\d,]*(?:\.\d+)?)\s*(naira|pounds?|dollars?|euros?|gbp|usd|ngn|eur)?",
                          part, re.IGNORECASE)
            if not m:
                continue
            amt = float(m.group(2).replace(",", ""))
            cur = SYMBOL_MAP.get(m.group(1) or "") or WORD_MAP.get((m.group(3) or "").lower()) or default_cur
            name = self._clean_name(part[: m.start()] + " " + part[m.end():])
            if name:
                items.append({"item": name, "amount": amt, "currency": cur,
                              "quantity": qty, "category": category})
        return items

    @staticmethod
    def _extract_category(part: str) -> Tuple[Optional[str], str]:
        """Pull an explicit category tag — "[shopping]", "(transport)", "#health" —
        off an item phrase. Returns (canonical_category_or_None, remaining_text)."""
        for m in re.finditer(r"[\[(]\s*([a-zA-Z &]+?)\s*[\])]|#([a-zA-Z&]+)", part):
            tag = (m.group(1) or m.group(2) or "").strip().lower()
            cat = _CATEGORY_TAGS.get(tag)
            if cat:
                return cat, part[: m.start()] + " " + part[m.end():]
        return None, part

    @staticmethod
    def _extract_qty(part: str) -> Tuple[float, str]:
        """Pull a leading/trailing quantity off an item phrase.

        Handles "3 ginger at 250", "2x ginger 250", "ginger x2 250". Returns
        (quantity, remaining_text); defaults to 1 and leaves the text untouched.
        """
        # "2x ginger" / "2 x ginger" at the start.
        m = re.match(r"\s*(\d+)\s*x\b\s*", part, re.IGNORECASE)
        if m:
            return float(m.group(1)), part[m.end():]
        # "ginger x2" anywhere.
        m = re.search(r"\bx\s*(\d+)\b", part, re.IGNORECASE)
        if m:
            return float(m.group(1)), part[: m.start()] + " " + part[m.end():]
        # Leading count immediately followed by a word: "3 ginger ...".
        m = re.match(r"\s*(\d+)\s+(?=[a-zA-Z])", part)
        if m:
            return float(m.group(1)), part[m.end():]
        return 1.0, part

    @staticmethod
    def _clean_name(text: str) -> str:
        words = [w for w in re.sub(r"[^a-zA-Z ]", " ", text).split() if w.lower() not in _STOP_WORDS and len(w) >= 2]
        return " ".join(words).strip().title()

    def _name_in(self, message: str, user_id: str, space: str) -> Optional[str]:
        low = message.lower()
        # Prefer an existing list mentioned by name.
        for lst in self.db.list_shopping_lists(user_id, space):
            if re.search(r"\b" + re.escape(lst["list_name"].lower()) + r"\b", low):
                return lst["list_name"]
        # "<name> list" pattern.
        m = re.search(r"\b([a-z][a-z ]*?)\s+(?:shopping |price )?list\b", low)
        if m:
            n = self._clean_name(m.group(1))
            if n:
                return n
        # "... to/for <name>" at the end.
        m2 = re.search(r"\b(?:to|for|on)\s+(?:the |my )?([a-z][a-z]+)\b\s*$", low)
        if m2:
            return self._clean_name(m2.group(1)) or None
        return None

    def _render(self, user_id: str, space: str, name: str, header: str = "") -> str:
        from collections import defaultdict
        items = self.db.get_shopping_items(user_id, space, name)
        lines = [header] if header else []
        lines.append(f"🛒 {name} · {len(items)} item{'s' if len(items) != 1 else ''}")
        if not items:
            lines.append("  (empty — add items like “ginger 500”)")
            return "\n".join(lines)
        totals: Dict[str, float] = defaultdict(float)
        for it in items:
            unit, cur = it.get("amount") or 0, it.get("currency", "GBP")
            qty = it.get("quantity") or 1
            line_total = unit * qty
            totals[cur] += line_total
            tag = f"  [{it['category']}]" if it.get("category") else ""
            if qty != 1:
                label = f"{self._qty_str(qty)}× {it['item']}"
                lines.append(f"  • {label:<18} {format_amount(line_total, cur)}  ({format_amount(unit, cur)} ea){tag}")
            else:
                lines.append(f"  • {it['item']:<18} {format_amount(line_total, cur)}{tag}")
        lines.append("  " + "─" * 26)
        lines.append("  Estimated  " + " · ".join(format_amount(v, k) for k, v in totals.items()))
        # Trip budget (set inline for this list), compared to the running estimate.
        budget = self.db.get_active_list_budget(user_id)
        if budget is not None and self.db.get_active_list(user_id) and \
                self.db.get_active_list(user_id).lower() == name.lower():
            cur = self.currency_fn(user_id, space)
            est = totals.get(cur, sum(totals.values()))
            left = budget - est
            if left < 0:
                lines.append(f"  🎯 Budget {format_amount(budget, cur)} · ⚠️ over by {format_amount(-left, cur)}")
            else:
                lines.append(f"  🎯 Budget {format_amount(budget, cur)} · {format_amount(left, cur)} left")
        lines.append("\nSay “done” to save, or “bought " + name + "” when you’ve paid.")
        return "\n".join(lines)

    def _render_all(self, user_id: str, space: str) -> str:
        lists = self.db.list_shopping_lists(user_id, space)
        if not lists:
            return "🛒 No shopping lists yet. Try “start a chai list: ginger 500, milk 1200”."
        lines = ["🛒 Your lists:"]
        for l in lists:
            lines.append(f"  • {l['list_name']} — {l['n']} items, est. {format_amount(l['total'] or 0, self.currency_fn(user_id, space))}")
        return "\n".join(lines)

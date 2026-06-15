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
            return ("buy", name, [{"item": i["item"],
                                   "amount": (i["amount"] or 0) * (i.get("quantity") or 1),
                                   "currency": i.get("currency", "GBP")} for i in items])

        # Clear / delete a list.
        if re.search(r"\b(clear|empty|delete|cancel|scrap)\b.*\blist\b", low):
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
            # any items mentioned inline (after ':' / 'with' / the word list)
            inline = message.split(":", 1)[1] if ":" in message else re.split(r"\bwith\b|\blist\b", message, flags=re.I)[-1]
            items = self._parse_items(inline, self.currency_fn(user_id, space))
            for it in items:
                self.db.add_shopping_item(user_id, space, name, it["item"], it["amount"], it["currency"], it["quantity"])
            head = f"🛒 Started “{name}”." + ("" if items else " Add items like “ginger 500, milk 1200”, then say “done”.")
            return ("reply", self._render(user_id, space, name, header=head))

        # Explicit add: "add ginger 500, milk 1200 to chai"
        if re.search(r"\badd\b.*\bto\b.*\blist\b", low) or (re.search(r"\badd\b", low) and self._name_in(message, user_id, space)):
            name = self._name_in(message, user_id, space) or active
            if not name:
                return ("reply", "Add to which list? e.g. “add ginger 500 to chai list”.")
            self.db.set_active_list(user_id, name)
            return self._add(message, user_id, space, name)

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

    # -- helpers ------------------------------------------------------------

    def _add(self, message: str, user_id: str, space: str, name: str) -> Signal:
        items = self._parse_items(self._strip_list_ref(message, name), self.currency_fn(user_id, space))
        if not items:
            return ("reply", "I didn’t catch an item + price. Try “ginger 500, milk 1200”.")
        for it in items:
            self.db.add_shopping_item(user_id, space, name, it["item"], it["amount"], it["currency"], it["quantity"])
        added = ", ".join(self._item_label(i) for i in items)
        return ("reply", self._render(user_id, space, name, header=f"➕ Added {added}"))

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
            qty, part = self._extract_qty(part)
            m = re.search(r"([£$€₦])?\s*(\d[\d,]*(?:\.\d+)?)\s*(naira|pounds?|dollars?|euros?|gbp|usd|ngn|eur)?",
                          part, re.IGNORECASE)
            if not m:
                continue
            amt = float(m.group(2).replace(",", ""))
            cur = SYMBOL_MAP.get(m.group(1) or "") or WORD_MAP.get((m.group(3) or "").lower()) or default_cur
            name = self._clean_name(part[: m.start()] + " " + part[m.end():])
            if name:
                items.append({"item": name, "amount": amt, "currency": cur, "quantity": qty})
        return items

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
            if qty != 1:
                label = f"{self._qty_str(qty)}× {it['item']}"
                lines.append(f"  • {label:<18} {format_amount(line_total, cur)}  ({format_amount(unit, cur)} ea)")
            else:
                lines.append(f"  • {it['item']:<18} {format_amount(line_total, cur)}")
        lines.append("  " + "─" * 26)
        lines.append("  Estimated  " + " · ".join(format_amount(v, k) for k, v in totals.items()))
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

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

    def _storage(self):
        """Return a storage adapter from any registered plugin that has one."""
        for plugin in self.router._registry.values():
            db = getattr(plugin, "db", None)
            if db is not None:
                return db
        return None

    def process(self, message: str, user_id: str = "default") -> ProcessingResult:
        """
        Process a natural language message end-to-end.

        Returns a ProcessingResult with the stored record and human response.
        """
        start = time.perf_counter()

        try:
            # Step -1: Resolve the Budget Space (prefix override or active space).
            space, message = self._resolve_space(message, user_id)

            # Step 0: Is this a correction to an existing entry, or a new one?
            classification = self.corrector.classify(message, self.memory.recent(domain="finance"))
            intent = classification.get("intent", "RECORD_NEW")
            if intent in ("UPDATE_EXISTING", "DELETE_EXISTING"):
                return self._handle_correction(intent, classification, user_id, message, start)

            # Step 1: Parse intent and extract entities
            record = self.parser.parse(message)
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

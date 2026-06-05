"""
Anthropic Claude client for OpenClaw.

Uses prompt caching (cache_control) on system prompts to reduce token costs.
Configured for deterministic extraction: temperature=0, max_tokens=1024.
"""

import logging
from typing import Optional

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a structured data extraction engine for OpenClaw.
Do not add commentary or explanations.
Only output valid JSON matching the schema requested.
If uncertain about a field, mark confidence low (below 0.6) and use null for the field value.
Never hallucinate merchant names, amounts, or dates that are not in the input.
Extract only what is explicitly stated or can be confidently inferred."""


class AnthropicClient:
    """
    Claude-backed LLM client with prompt caching.

    Falls back to a mock if anthropic SDK is not installed (for testing).
    """

    DEFAULT_MODEL = "claude-haiku-4-5-20251001"  # Fast + cheap for extraction tasks

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        if not _ANTHROPIC_AVAILABLE:
            raise ImportError("anthropic package not installed. Run: pip install anthropic")

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model or self.DEFAULT_MODEL

    def complete(self, prompt: str) -> str:
        """Send prompt to Claude and return text response."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                temperature=0,  # Deterministic extraction
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},  # Cache system prompt
                    }
                ],
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            logger.error("Anthropic API error: %s", e)
            raise


class MockLLMClient:
    """
    Deterministic mock LLM client for testing and offline use.
    Returns pre-canned JSON responses based on simple heuristics.
    """

    def complete(self, prompt: str) -> str:
        import json
        import re
        from datetime import datetime

        prompt_lower = prompt.lower()

        # Classify/extract based ONLY on the embedded user message — never the
        # surrounding prompt template, which itself contains words like "income".
        msg_match = re.search(r"Message:\s*(.+?)(?:\n|$)", prompt)
        original_msg = msg_match.group(1).strip() if msg_match else ""
        msg_lower = original_msg.lower()

        # Correction-classification prompt (heuristic): new vs update vs delete.
        if "RECORD_NEW" in prompt and "UPDATE_EXISTING" in prompt:
            um = re.search(r"USER INPUT:\s*(.+?)(?:\n|$)", prompt)
            umsg = (um.group(1) if um else "").strip()
            uml = umsg.lower()
            amounts = [float(x) for x in re.findall(r"[£$€](\d+(?:\.\d+)?)", umsg)]
            if any(w in uml for w in ["delete", "remove", "cancel", "scratch", "void"]):
                return json.dumps({
                    "intent": "DELETE_EXISTING",
                    "target_search_criteria": {
                        "approximate_old_amount": amounts[0] if amounts else None,
                        "old_description_keyword": None,
                    },
                })
            if any(w in uml for w in ["actually", "change", "should be", "wrong", "correct",
                                      "meant", "instead", "not ", "update", "fix", "categor"]):
                updates = {"amount": None, "description": None, "category": None}
                old_amt = None
                if len(amounts) >= 2:
                    old_amt, updates["amount"] = amounts[0], amounts[1]
                elif len(amounts) == 1:
                    updates["amount"] = amounts[0]
                for kw, cat in [("food", "Food & Drink"), ("transport", "Transport"),
                                ("shopping", "Shopping"), ("utilities", "Utilities"),
                                ("entertainment", "Entertainment"), ("health", "Health"),
                                ("education", "Education"), ("rent", "Rent")]:
                    if kw in uml:
                        updates["category"] = cat
                return json.dumps({
                    "intent": "UPDATE_EXISTING",
                    "target_search_criteria": {"approximate_old_amount": old_amt, "old_description_keyword": None},
                    "updates": updates,
                })
            return json.dumps({"intent": "RECORD_NEW"})

        # Intent classification prompt
        if "classify" in prompt_lower or "intents" in prompt_lower:
            if any(w in msg_lower for w in ["spent", "bought", "paid for", "cost", "purchase"]):
                return json.dumps({
                    "intents": ["expense"],
                    "primary_intent": "expense",
                    "confidence": 0.92,
                    "domain": "finance",
                })
            if any(w in msg_lower for w in ["received", "earned", "salary", "income", "paid me", "invoice", "freelance", "consulting", "dividend", "client paid"]):
                return json.dumps({
                    "intents": ["income"],
                    "primary_intent": "income",
                    "confidence": 0.90,
                    "domain": "finance",
                })
            return json.dumps({
                "intents": ["general_note"],
                "primary_intent": "general_note",
                "confidence": 0.5,
                "domain": "general",
            })

        # Determine type from classification context in prompt
        type_match = re.search(r"type:\s*(\w+)", prompt)
        record_type = type_match.group(1) if type_match else "expense"
        if record_type not in ("expense", "income", "task", "event", "inventory_update",
                               "care_log", "education_record", "property_transaction", "general_note"):
            record_type = "expense"

        # Find amount
        amount_match = re.search(r"[£$€](\d+(?:\.\d+)?)", original_msg or prompt)
        amount = float(amount_match.group(1)) if amount_match else None

        # Find merchant (word after "at" or "from")
        merchant_match = re.search(r"\b(?:at|from|in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", original_msg or prompt)
        merchant = merchant_match.group(1) if merchant_match else None

        return json.dumps({
            "domain": "finance",
            "type": record_type,
            "timestamp": None,
            "entities": {
                "merchant": merchant,
                "category": "Other",
                "tags": [],
                "notes": None,
            },
            "amount": amount,
            "currency": "GBP",
            "description": original_msg or "Recorded entry",
            "raw_input": original_msg,
            "confidence": 0.85,
        })


class MockVisionClient:
    """Offline vision client for tests/--mock: returns a canned document payload."""

    def __init__(self, response: Optional[str] = None):
        import json
        self._response = response or json.dumps({
            "action": "RECORD_NEW",
            "type": "expense",
            "amount": 2.15,
            "currency": "GBP",
            "description": "Tesco Superstore (receipt)",
            "category": "Groceries",
        })

    def complete_vision(self, prompt: str, image_b64: str, mime: str = "image/jpeg") -> str:
        return self._response

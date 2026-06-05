"""
Document parser — turns an image (receipt, invoice, payslip, bank screenshot,
handwritten memo) into a structured finance record using a vision LLM.

The heavy lifting (classification + extraction) is delegated to the vision model
via DOCUMENT_PARSING_PROMPT; this module normalises the model's JSON into the
internal record contract and applies deterministic guards.
"""

import json
import logging
import re
from typing import Any, Dict

from openclaw.llm.prompt_templates import DOCUMENT_PARSING_PROMPT

logger = logging.getLogger(__name__)

_VALID_CATEGORIES = {
    "Groceries", "Food & Drink", "Shopping", "Utilities", "Income", "Transport",
    "Entertainment", "Health", "Education", "Rent", "Salary", "Freelance", "Investment", "Other",
}


class DocumentParser:
    def __init__(self, vision_client):
        self.vision = vision_client

    def parse(self, image_b64: str, mime: str = "image/jpeg") -> Dict[str, Any]:
        raw = self.vision.complete_vision(DOCUMENT_PARSING_PROMPT, image_b64, mime)
        data = self._parse_json(raw)

        rtype = data.get("type") if data.get("type") in ("expense", "income") else "expense"
        amount = data.get("amount")
        try:
            amount = float(amount) if amount is not None else None
        except (TypeError, ValueError):
            amount = None

        currency = data.get("currency") if data.get("currency") in ("GBP", "USD", "EUR") else "GBP"
        category = data.get("category") if data.get("category") in _VALID_CATEGORIES else "Other"
        description = (data.get("description") or "Scanned document").strip()

        return {
            "domain": "finance",
            "type": rtype,
            "amount": amount,
            "currency": currency,
            "description": description,
            "entities": {"category": category, "source": "image"},
            "raw_input": "[image]",
            "confidence": 0.8,
            "intents": [rtype],
            "primary_intent": rtype,
        }

    @staticmethod
    def _parse_json(raw: str) -> Dict[str, Any]:
        text = (raw or "").strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        logger.error("Document JSON parse failed. Raw: %s", (raw or "")[:200])
        return {}

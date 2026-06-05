"""
Intent Parser — classifies user messages and extracts structured records.

Uses the configured LLM client to perform two-pass extraction:
  1. Intent classification
  2. Entity extraction into a validated record dict
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

from openclaw.llm.prompt_templates import (
    ENTITY_EXTRACTION_PROMPT,
    INTENT_CLASSIFICATION_PROMPT,
)
from openclaw.llm.function_schemas import VALID_INTENTS, VALID_DOMAINS
from openclaw.utils.date_parser import parse_datetime
from openclaw.utils.currency_normalizer import extract_amount_and_currency

logger = logging.getLogger(__name__)

# Detects an explicit currency symbol or 3-letter code in free text.
_EXPLICIT_CURRENCY_RE = re.compile(
    r"[£$€¥₹₩]|\b(?:GBP|USD|EUR|JPY|INR|CHF|SEK|PLN|ZAR|AUD|CAD|NZD)\b",
    re.IGNORECASE,
)


def _has_explicit_currency(text: str) -> bool:
    return bool(_EXPLICIT_CURRENCY_RE.search(text))


class IntentParser:
    """Two-pass LLM-based intent classifier and entity extractor."""

    CONFIDENCE_THRESHOLD = 0.5

    def __init__(self, llm_client):
        self.llm = llm_client

    def parse(self, message: str) -> Dict[str, Any]:
        """
        Parse a natural language message into a structured record.

        Returns a record dict conforming to the OpenClaw record contract.
        Raises ValueError if classification confidence is below threshold.
        """
        now = datetime.now()

        # Pass 1: classify intent and domain
        intent_result = self._classify_intent(message)

        if intent_result["confidence"] < self.CONFIDENCE_THRESHOLD:
            logger.warning("Low confidence intent: %.2f for '%s'", intent_result["confidence"], message)

        # Pass 2: extract entities
        record = self._extract_entities(
            message=message,
            domain=intent_result["domain"],
            intent_type=intent_result["primary_intent"],
            now=now,
        )

        # Merge intent metadata into record. Classification is authoritative for
        # domain/type — entity extraction must not silently override the route
        # (e.g. defaulting domain to "finance" for a general note).
        record["intents"] = intent_result["intents"]
        record["primary_intent"] = intent_result["primary_intent"]
        record["domain"] = intent_result["domain"]
        record["type"] = intent_result["primary_intent"]

        # Resolve timestamp (LLM may return null or relative string)
        if not record.get("timestamp"):
            record["timestamp"] = now.isoformat()
        else:
            record["timestamp"] = parse_datetime(record["timestamp"], now).isoformat()

        # Reconcile amount/currency with the deterministic extractor.
        detected_amount, detected_currency = extract_amount_and_currency(message)
        if record.get("amount") is None and detected_amount is not None:
            record["amount"] = detected_amount
            record["currency"] = detected_currency
        elif _has_explicit_currency(message):
            # An explicit symbol/code in the message overrides the LLM's default.
            record["currency"] = detected_currency

        return record

    def _classify_intent(self, message: str) -> Dict[str, Any]:
        prompt = INTENT_CLASSIFICATION_PROMPT.format(message=message)
        raw = self.llm.complete(prompt)
        result = self._parse_json(raw)

        # Validate and sanitise
        result.setdefault("intents", ["general_note"])
        result.setdefault("primary_intent", "general_note")
        result.setdefault("confidence", 0.5)
        result.setdefault("domain", "general")

        # Clamp to known values
        result["intents"] = [i for i in result["intents"] if i in VALID_INTENTS] or ["general_note"]
        result["primary_intent"] = result["primary_intent"] if result["primary_intent"] in VALID_INTENTS else result["intents"][0]
        result["domain"] = result["domain"] if result["domain"] in VALID_DOMAINS else "general"
        result["confidence"] = max(0.0, min(1.0, float(result["confidence"])))

        return result

    def _extract_entities(
        self,
        message: str,
        domain: str,
        intent_type: str,
        now: datetime,
    ) -> Dict[str, Any]:
        prompt = ENTITY_EXTRACTION_PROMPT.format(
            domain=domain,
            intent_type=intent_type,
            message=message,
            today=now.strftime("%Y-%m-%d %H:%M"),
        )
        raw = self.llm.complete(prompt)
        record = self._parse_json(raw)

        # Ensure mandatory fields exist
        record.setdefault("domain", domain)
        record.setdefault("type", intent_type)
        record.setdefault("entities", {})
        record.setdefault("amount", None)
        record.setdefault("currency", "GBP")
        record.setdefault("description", message[:120])
        record.setdefault("raw_input", message)
        record.setdefault("confidence", 0.5)

        return record

    @staticmethod
    def _parse_json(raw: str) -> Dict[str, Any]:
        """Extract JSON from LLM response, tolerating markdown code fences."""
        text = raw.strip()
        # Strip ```json ... ``` fences
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Open models sometimes wrap JSON in prose — extract the outermost object.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        logger.error("JSON parse error. Raw: %s", raw[:300])
        return {}

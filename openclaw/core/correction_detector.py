"""
Correction detector.

Decides whether an incoming message is a brand-new entry (RECORD_NEW) or a
correction to a previously logged item (UPDATE_EXISTING / DELETE_EXISTING).

To avoid adding LLM latency to the common case (new entries), a cheap keyword
prefilter runs first: only messages that *look like* corrections are sent to the
LLM classifier. Everything else short-circuits to RECORD_NEW so the normal
parsing pipeline handles it unchanged.
"""

import json
import logging
import re
from typing import Any, Dict, List

from openclaw.llm.prompt_templates import CORRECTION_CLASSIFICATION_PROMPT

logger = logging.getLogger(__name__)

# If none of these appear, the message is treated as a new entry without an LLM call.
_CORRECTION_HINTS = re.compile(
    r"\b(actually|no it was|should be|should've been|change|correct(?:ion)?|wrong|"
    r"mistake|meant|instead|not\s*[£$€]|delete|remove|cancel|scratch that|undo|"
    r"edit|update the|fix|that was wrong|miscategor|recategor)\b",
    re.IGNORECASE,
)


class CorrectionDetector:
    def __init__(self, llm_client):
        self.llm = llm_client

    def looks_like_correction(self, message: str) -> bool:
        return bool(_CORRECTION_HINTS.search(message))

    def classify(self, message: str, recent: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Return the correction-classification JSON. Defaults to RECORD_NEW."""
        if not self.looks_like_correction(message):
            return {"intent": "RECORD_NEW"}

        prompt = CORRECTION_CLASSIFICATION_PROMPT.format(
            recent_entries=self._format_recent(recent),
            message=message,
        )
        try:
            raw = self.llm.complete(prompt)
            result = self._parse_json(raw)
        except Exception as e:
            logger.warning("Correction classification failed (%s) — treating as new entry", e)
            return {"intent": "RECORD_NEW"}

        if result.get("intent") not in ("RECORD_NEW", "UPDATE_EXISTING", "DELETE_EXISTING"):
            return {"intent": "RECORD_NEW"}
        return result

    @staticmethod
    def _format_recent(recent: List[Dict[str, Any]], n: int = 10) -> str:
        if not recent:
            return "(none)"
        lines = []
        for r in recent[:n]:
            amt = r.get("amount")
            cat = r.get("entities", {}).get("category", "")
            lines.append(f"- {r.get('description', '')} | amount={amt} | category={cat}")
        return "\n".join(lines)

    @staticmethod
    def _parse_json(raw: str) -> Dict[str, Any]:
        text = raw.strip()
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
        logger.error("Correction JSON parse failed. Raw: %s", raw[:200])
        return {"intent": "RECORD_NEW"}

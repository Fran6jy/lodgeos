"""
Domain Router — maps parsed records to the correct domain plugin.

Supports:
- direct domain routing
- multi-domain routing (record split across plugins)
- fallback routing when confidence is low
- configurable confidence threshold
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class Router:
    """Routes records to registered domain plugins."""

    FALLBACK_DOMAIN = "general"
    MIN_CONFIDENCE = 0.4

    def __init__(self):
        self._registry: Dict[str, Any] = {}

    def register(self, domain: str, plugin) -> None:
        """Register a plugin for a domain."""
        self._registry[domain] = plugin
        logger.info("Registered plugin for domain: %s", domain)

    def route(self, record: Dict[str, Any]) -> Tuple[Any, str]:
        """
        Return (plugin, domain) for the given record.
        Falls back to general plugin if domain not registered or confidence too low.
        """
        domain = record.get("domain", self.FALLBACK_DOMAIN)
        confidence = record.get("confidence", 0.0)

        if confidence < self.MIN_CONFIDENCE:
            logger.warning(
                "Confidence %.2f below threshold — routing to fallback domain", confidence
            )
            domain = self.FALLBACK_DOMAIN

        plugin = self._registry.get(domain)
        if plugin is None:
            logger.warning("No plugin for domain %r — trying fallback", domain)
            plugin = self._registry.get(self.FALLBACK_DOMAIN)
            domain = self.FALLBACK_DOMAIN

        if plugin is None:
            raise RuntimeError(
                f"No plugin registered for domain {domain!r} and no fallback available."
            )

        return plugin, domain

    def route_multi(self, record: Dict[str, Any]) -> List[Tuple[Any, str]]:
        """
        Route to multiple plugins when record has multiple intents spanning domains.
        Returns list of (plugin, domain) pairs.
        """
        intents = record.get("intents", [])
        routes = []
        seen = set()

        for intent in intents:
            domain = self._intent_to_domain(intent)
            if domain in seen:
                continue
            seen.add(domain)
            plugin = self._registry.get(domain)
            if plugin:
                routes.append((plugin, domain))

        if not routes:
            plugin, domain = self.route(record)
            routes = [(plugin, domain)]

        return routes

    @staticmethod
    def _intent_to_domain(intent: str) -> str:
        mapping = {
            "expense": "finance",
            "income": "finance",
            "property_transaction": "property",
            "education_record": "education",
            "care_log": "healthcare",
            "inventory_update": "inventory",
            "task": "personal_life",
            "event": "personal_life",
            "general_note": "general",
        }
        return mapping.get(intent, "general")

    def list_domains(self) -> List[str]:
        return list(self._registry.keys())

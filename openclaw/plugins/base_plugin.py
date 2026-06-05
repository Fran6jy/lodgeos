"""Base plugin contract. All domain plugins must implement this interface."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BasePlugin(ABC):
    """Abstract base for all domain plugins."""

    domain: str = "base"

    @abstractmethod
    def validate(self, record: Dict[str, Any]) -> bool:
        """Domain-specific validation beyond schema. Return True if valid."""

    @abstractmethod
    def transform(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich, normalise, or compute derived fields. Return modified record."""

    @abstractmethod
    def store(self, record: Dict[str, Any]) -> str:
        """Persist the record. Return the record's ID."""

    @abstractmethod
    def query(self, request: str) -> str:
        """Handle a natural language query against stored records. Return text response."""

    @abstractmethod
    def summarize(self, timeframe: str) -> str:
        """Return a human-readable summary for the given timeframe (day/week/month)."""

    def build_response(self, record: Dict[str, Any], memory=None) -> str:
        """
        Build the confirmation message shown to the user after storing a record.
        Plugins should override this for domain-specific responses.
        """
        return f"✓ Recorded {record.get('type', 'entry')}: {record.get('description', '')}"

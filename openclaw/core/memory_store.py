"""
In-memory session context store.

Holds recent records within a session for:
- budget comparisons
- follow-up query context
- deduplication hints
"""

from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional


class MemoryStore:
    """Lightweight in-session memory for recent records and context."""

    def __init__(self, max_records: int = 50):
        self._records: deque = deque(maxlen=max_records)
        self._session_start: datetime = datetime.now()
        self._context: Dict[str, Any] = {}

    def add(self, record: Dict[str, Any]) -> None:
        self._records.appendleft(record)

    def recent(self, n: int = 10, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        records = list(self._records)
        if domain:
            records = [r for r in records if r.get("domain") == domain]
        return records[:n]

    def set_context(self, key: str, value: Any) -> None:
        self._context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        return self._context.get(key, default)

    def clear(self) -> None:
        self._records.clear()
        self._context.clear()

    @property
    def session_duration_seconds(self) -> float:
        return (datetime.now() - self._session_start).total_seconds()

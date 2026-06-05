"""
Fallback LLM client — chains multiple providers for resilience.

Tries providers in priority order (e.g. Anthropic → OpenRouter → Mock). The
first provider to return successfully becomes "sticky": subsequent calls try it
first, so a dead provider (no credit) isn't re-hit on every request. If it later
fails, the chain falls through to the next provider again.

This is what lets OpenClaw keep working when the primary API is unavailable.
"""

import logging
from typing import Any, List, Tuple

logger = logging.getLogger(__name__)


class FallbackLLMClient:
    """Wraps an ordered list of (name, client) and routes `.complete()` through them."""

    def __init__(self, clients: List[Tuple[str, Any]]):
        if not clients:
            raise ValueError("FallbackLLMClient requires at least one client.")
        self._clients = clients
        self._preferred = 0  # index of the last-known-good client

    @property
    def active_provider(self) -> str:
        return self._clients[self._preferred][0]

    def complete(self, prompt: str) -> str:
        # Try the sticky preferred client first, then the rest in order.
        order = [self._preferred] + [i for i in range(len(self._clients)) if i != self._preferred]

        last_err: Exception | None = None
        for i in order:
            name, client = self._clients[i]
            try:
                result = client.complete(prompt)
                if i != self._preferred:
                    logger.info("LLM provider switched to '%s'", name)
                    self._preferred = i
                return result
            except Exception as e:
                last_err = e
                logger.warning("LLM provider '%s' failed: %s", name, e)
                continue

        raise RuntimeError(f"All LLM providers failed. Last error: {last_err}")

"""
LLM client factory.

Builds the LLM client used across all integrations (CLI, Telegram, API) from
environment configuration, with automatic provider fallback:

    Anthropic (if ANTHROPIC_API_KEY)  →  OpenRouter (if OPENROUTER_API_KEY)  →  error

Mock mode (use_mock=True or OPENCLAW_MOCK=1) bypasses everything and returns the
offline deterministic client — no API key, no cost.
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def build_llm_client(use_mock: bool = False, api_key: str | None = None) -> Any:
    """Return an LLM client. Chains real providers; falls back across them."""
    if use_mock or os.environ.get("OPENCLAW_MOCK") == "1":
        from openclaw.llm.anthropic_client import MockLLMClient
        return MockLLMClient()

    from openclaw.llm.fallback_client import FallbackLLMClient

    clients: list[tuple[str, Any]] = []

    anthropic_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            from openclaw.llm.anthropic_client import AnthropicClient
            clients.append(("anthropic", AnthropicClient(api_key=anthropic_key)))
        except ImportError:
            logger.warning("anthropic SDK not installed — skipping Anthropic provider")

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        from openclaw.llm.openrouter_client import OpenRouterClient
        model = os.environ.get("OPENROUTER_MODEL")  # optional override
        clients.append(("openrouter", OpenRouterClient(api_key=openrouter_key, model=model)))

    if not clients:
        raise RuntimeError(
            "No LLM provider configured. Set ANTHROPIC_API_KEY or OPENROUTER_API_KEY, "
            "or run in mock mode (--mock)."
        )

    if len(clients) == 1:
        logger.info("LLM provider: %s", clients[0][0])
        return clients[0][1]

    logger.info("LLM providers (in fallback order): %s", ", ".join(n for n, _ in clients))
    return FallbackLLMClient(clients)


def build_vision_client(use_mock: bool = False) -> Any:
    """Return a vision-capable client (has .complete_vision). OpenRouter or mock."""
    if use_mock or os.environ.get("OPENCLAW_MOCK") == "1":
        from openclaw.llm.anthropic_client import MockVisionClient
        return MockVisionClient()

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if not openrouter_key:
        raise RuntimeError(
            "Image parsing needs a vision model. Set OPENROUTER_API_KEY "
            "(optionally OPENROUTER_VISION_MODEL), or run in mock mode."
        )
    from openclaw.llm.openrouter_client import OpenRouterClient
    return OpenRouterClient(
        api_key=openrouter_key,
        vision_model=os.environ.get("OPENROUTER_VISION_MODEL"),
    )

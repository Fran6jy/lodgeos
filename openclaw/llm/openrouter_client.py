"""
OpenRouter LLM client — OpenAI-compatible fallback for OpenClaw.

Used when the Anthropic API is unavailable (e.g. no credit). Talks to
OpenRouter's chat-completions endpoint using only the standard library, so it
adds no dependencies. Free models (``:free`` suffix) are frequently rate
limited upstream, so requests retry on HTTP 429 with backoff.

Set OPENROUTER_API_KEY (and optionally OPENROUTER_MODEL) in the environment.
"""

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Optional

from openclaw.llm.anthropic_client import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterClient:
    """Minimal OpenRouter client exposing the same `.complete(prompt)` interface."""

    DEFAULT_MODEL = "openai/gpt-oss-20b:free"
    MAX_RETRIES = 4
    RETRY_BACKOFF_S = 3

    # Free vision models tried in order — independent rate limits, so falling
    # through to the next when one is saturated greatly improves reliability.
    DEFAULT_VISION_MODELS = [
        "google/gemma-4-26b-a4b-it:free",
        "moonshotai/kimi-k2.6:free",
        "nvidia/nemotron-nano-12b-v2-vl:free",
    ]

    def __init__(self, api_key: str, model: Optional[str] = None, vision_model: Optional[str] = None):
        if not api_key:
            raise ValueError("OpenRouter API key is required.")
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        # A single override (env) takes priority; otherwise use the fallback list.
        self.vision_models = [vision_model] if vision_model else list(self.DEFAULT_VISION_MODELS)

    def complete(self, prompt: str) -> str:
        return self._chat([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ], model=self.model)

    def complete_vision(self, prompt: str, image_b64: str, mime: str = "image/jpeg") -> str:
        """Send a prompt + image to a vision model, falling through the model list."""
        data_url = f"data:{mime};base64,{image_b64}"
        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ]
        last_err: Optional[Exception] = None
        for model in self.vision_models:
            try:
                return self._chat(messages, model=model)
            except Exception as e:
                last_err = e
                logger.warning("Vision model %s unavailable — trying next", model)
        raise RuntimeError(f"All vision models failed. Last error: {last_err}")

    def _chat(self, messages, model: str) -> str:
        body = json.dumps({
            "model": model,
            "temperature": 0,  # deterministic extraction
            "messages": messages,
        }).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # OpenRouter attribution headers (optional but recommended).
            "HTTP-Referer": "https://github.com/openclaw",
            "X-Title": "OpenClaw",
        }

        last_err: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES):
            req = urllib.request.Request(ENDPOINT, data=body, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.load(resp)
                return data["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code == 429:  # rate limited upstream — retry with backoff
                    logger.warning("OpenRouter 429 (attempt %d/%d) — retrying", attempt + 1, self.MAX_RETRIES)
                    time.sleep(self.RETRY_BACKOFF_S)
                    continue
                detail = e.read().decode("utf-8", "ignore")[:200]
                logger.error("OpenRouter HTTP %s: %s", e.code, detail)
                raise
            except (urllib.error.URLError, KeyError, TimeoutError) as e:
                last_err = e
                logger.warning("OpenRouter error (attempt %d/%d): %s", attempt + 1, self.MAX_RETRIES, e)
                time.sleep(self.RETRY_BACKOFF_S)

        raise RuntimeError(f"OpenRouter failed after {self.MAX_RETRIES} attempts: {last_err}")

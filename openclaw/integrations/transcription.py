"""
Voice transcription with a local/cloud toggle.

Speech-to-text for voice notes, switchable by configuration:

    WHISPER_MODE=local   →  faster-whisper, runs on your machine, free (default)
    WHISPER_MODE=cloud   →  managed OpenAI-compatible endpoint (OpenAI, Groq, …)

Local mode is ideal while building (no API cost, no network). Flip to cloud
once the app is deployed so the server doesn't carry the model. Nothing else in
the codebase changes — only the config.

Local mode requires:   pip install faster-whisper
Cloud mode requires:   WHISPER_CLOUD_API_KEY (+ optional base URL / model)
"""

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

logger = logging.getLogger(__name__)


class Transcriber(Protocol):
    def transcribe(self, audio: bytes, suffix: str = ".ogg") -> str: ...


@dataclass
class TranscriptionConfig:
    """All transcription settings — the single operational toggle lives here."""

    mode: str = "local"  # "local" | "cloud"

    # Local (faster-whisper)
    local_model: str = "base"          # tiny | base | small | medium | large-v3
    local_device: str = "cpu"          # "cpu" | "cuda"
    local_compute_type: str = "int8"   # int8 is fast/light on CPU

    # Cloud (OpenAI-compatible audio/transcriptions)
    cloud_base_url: str = "https://api.groq.com/openai/v1"
    cloud_api_key: Optional[str] = None
    cloud_model: str = "whisper-large-v3"

    # Accuracy tuning (both modes)
    language: str = "en"
    # Vocabulary bias: nudges Whisper toward finance/currency words it otherwise
    # mishears (e.g. "naira" → "NIRROR"). Override/extend via WHISPER_PROMPT.
    prompt: str = ("Personal finance voice note. Amounts and currencies like "
                   "naira, pounds, dollars, euros, cedis. Words: spent, paid, "
                   "transport, transcript, registry, groceries, rent, salary.")

    @classmethod
    def from_env(cls) -> "TranscriptionConfig":
        return cls(
            mode=os.environ.get("WHISPER_MODE", "local").lower(),
            local_model=os.environ.get("WHISPER_LOCAL_MODEL", "base"),
            local_device=os.environ.get("WHISPER_LOCAL_DEVICE", "cpu"),
            local_compute_type=os.environ.get("WHISPER_LOCAL_COMPUTE", "int8"),
            cloud_base_url=os.environ.get("WHISPER_CLOUD_BASE_URL", "https://api.groq.com/openai/v1"),
            cloud_api_key=os.environ.get("WHISPER_CLOUD_API_KEY"),
            cloud_model=os.environ.get("WHISPER_CLOUD_MODEL", "whisper-large-v3"),
            language=os.environ.get("WHISPER_LANGUAGE", "en"),
            prompt=os.environ.get("WHISPER_PROMPT", cls.prompt),
        )


class LocalWhisperTranscriber:
    """Runs faster-whisper locally. Model is loaded lazily on first use."""

    def __init__(self, config: TranscriptionConfig):
        self.config = config
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise RuntimeError(
                    "Local transcription needs faster-whisper. "
                    "Install it (pip install faster-whisper) or set WHISPER_MODE=cloud."
                ) from e
            logger.info("Loading faster-whisper model '%s' (%s)…", self.config.local_model, self.config.local_device)
            self._model = WhisperModel(
                self.config.local_model,
                device=self.config.local_device,
                compute_type=self.config.local_compute_type,
            )
        return self._model

    def transcribe(self, audio: bytes, suffix: str = ".ogg") -> str:
        model = self._ensure_model()
        tmp = Path(tempfile.mkdtemp()) / f"voice{suffix}"
        tmp.write_bytes(audio)
        try:
            segments, _ = model.transcribe(
                str(tmp),
                language=self.config.language or None,
                initial_prompt=self.config.prompt or None,  # vocabulary bias
                beam_size=5,                      # better than greedy for accents
                vad_filter=True,                  # skip silence → fewer hallucinations
                condition_on_previous_text=False,  # stops runaway repetition
            )
            return " ".join(seg.text.strip() for seg in segments).strip()
        finally:
            tmp.unlink(missing_ok=True)


class CloudWhisperTranscriber:
    """Posts audio to a managed OpenAI-compatible transcription endpoint."""

    def __init__(self, config: TranscriptionConfig):
        if not config.cloud_api_key:
            raise RuntimeError("Cloud transcription needs WHISPER_CLOUD_API_KEY.")
        self.config = config

    def transcribe(self, audio: bytes, suffix: str = ".ogg") -> str:
        import httpx  # already present (Anthropic/Telegram dependency)

        url = self.config.cloud_base_url.rstrip("/") + "/audio/transcriptions"
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {self.config.cloud_api_key}"},
            files={"file": (f"voice{suffix}", audio, "audio/ogg")},
            data={"model": self.config.cloud_model,
                  "language": self.config.language or "en",
                  "prompt": self.config.prompt or ""},  # same vocabulary bias
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("text", "").strip()


def build_transcriber(config: Optional[TranscriptionConfig] = None) -> Transcriber:
    """Return a transcriber for the configured mode. The toggle is read here."""
    config = config or TranscriptionConfig.from_env()
    if config.mode == "cloud":
        logger.info("Transcription: CLOUD (%s, model=%s)", config.cloud_base_url, config.cloud_model)
        return CloudWhisperTranscriber(config)
    logger.info("Transcription: LOCAL faster-whisper (model=%s)", config.local_model)
    return LocalWhisperTranscriber(config)

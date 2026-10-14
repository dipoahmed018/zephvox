"""Provider (driver) contracts. Implement one of these to plug in a new engine."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, NamedTuple

import numpy as np
from pydantic import BaseModel, ConfigDict

from ..engine.capabilities import SystemCapabilities
from ..engine.models import AudioRef, Pronunciation, Transcript


class Availability(NamedTuple):
    ok: bool
    reason: str = ""


class ProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Download:
    """A model a provider needs, fetched by `speakcheck setup` ahead of first use."""

    source: str  # "huggingface" | "faster-whisper" | "ollama"
    name: str  # repo id, faster-whisper model name, or Ollama model
    approx_gb: float | None = None
    patterns: tuple[str, ...] | None = None  # huggingface: only these files


@dataclass
class Services:
    """What the engine offers a provider: system info and a way to build sibling providers."""

    caps: SystemCapabilities = field(default_factory=SystemCapabilities)
    build: Callable[[str, str], Provider] | None = None


class Provider:
    kind: ClassVar[str]
    name: ClassVar[str]
    Settings: ClassVar[type[ProviderSettings]] = ProviderSettings

    def __init__(self, settings: dict[str, Any] | None = None, services: Services | None = None):
        # Construction must be cheap: load models lazily on first use.
        self.settings = self.Settings(**(settings or {}))
        self.services = services or Services()

    def check_available(self) -> Availability:
        return Availability(True)

    def capabilities(self) -> dict[str, Any]:
        return {}

    def downloads(self) -> list[Download]:
        """Models this provider will fetch on first use, so setup can fetch them up front."""
        return []

    def prepare(self) -> None:
        """Get ready for use; called by the engine once, right before the provider is first used.

        Server-based drivers launch their server here (if configured to) and wait until it
        answers. Raise a SpeakcheckError if the provider can't be made ready; the engine then
        falls back to the next configured provider. In-process model drivers can leave this as is
        and load lazily.
        """

    def close(self) -> None:
        """Release models, and stop any process that `prepare()` launched (never one it didn't)."""


@dataclass(frozen=True)
class Device:
    id: str  # what goes into the driver's `device` setting
    name: str  # human-readable
    is_default: bool = False


class CaptureProvider(Provider):
    kind = "capture"

    def list_devices(self) -> list[Device]:
        """Input devices this driver can record from."""
        return []

    def level(self, handle: dict[str, Any]) -> float | None:
        """Current input level 0–1 of an active recording (None if unknown)."""
        return None

    def start(self, dest: Path) -> dict[str, Any]:
        """Start recording into `dest`; return a JSON-serializable handle for `stop()`.

        The handle may be used from a different process (CLI `start` / `stop`).
        """
        raise NotImplementedError

    def stop(self, handle: dict[str, Any]) -> AudioRef:
        raise NotImplementedError


class STTProvider(Provider):
    kind = "stt"

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> Transcript:
        """Must return word timestamps in `Segment.words` when capabilities()['word_timestamps']."""
        raise NotImplementedError


class G2PProvider(Provider):
    kind = "g2p"

    def pronounce(self, words: list[str]) -> dict[str, Pronunciation]:
        """Return a Pronunciation for every input word (empty `variants` if unknown).

        Phones must be canonical IPA (see `engine.phonemes.normalize`).
        """
        raise NotImplementedError


class PhonemeRecognizer(Provider):
    kind = "phonemes"

    def recognize(self, samples: np.ndarray, sample_rate: int) -> list[str]:
        """Return the canonical IPA phones heard in `samples`."""
        raise NotImplementedError

    def recognize_timed(self, samples: np.ndarray, sample_rate: int) -> list[tuple[str, float]] | None:
        """Optional: phones with the time (seconds into `samples`) each was heard.

        Lets analyzers attribute sounds to words by time instead of by alignment alone.
        Return None if the driver can't tell.
        """
        return None


class LLMProvider(Provider):
    kind = "llm"

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Return a JSON object matching `schema`, or raise LLMError."""
        raise NotImplementedError


class TTSProvider(Provider):
    kind = "tts"

    def synthesize(self, text: str) -> bytes:
        """Return WAV bytes of `text` spoken with a standard pronunciation."""
        raise NotImplementedError


class TriggerProvider(Provider):
    """Global shortcuts. Drivers translate key combos; actions are defined by the engine."""

    kind = "triggers"

    def start(self, bindings: dict[str, str], fire: Callable[[str], None]) -> None:
        """Register `bindings` ({action: "Ctrl+Alt+R"}) and call `fire(action)` when pressed.

        `fire` may be called from any thread.
        """
        raise NotImplementedError

    def stop(self) -> None:
        """Unregister the shortcuts."""

    def describe(self) -> str:
        """One sentence telling the user where/how they can rebind the shortcuts."""
        return ""

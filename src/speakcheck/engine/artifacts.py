"""Artifacts: intermediate data computed once per session, on demand.

Analyzers declare which artifacts they need; the planner works out which producers (and
therefore which providers) must run. Plugins can register new artifacts the same way.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import audio
from .errors import PlanError
from .events import EventBus
from .models import SAMPLE_RATE, PhoneSeq
from .text import normalize_word, split_into_sentences

SEGMENT_PAD_S = 0.15


@dataclass(frozen=True)
class ArtifactSpec:
    key: str
    produce: Callable[[ArtifactStore], Any]
    needs: tuple[str, ...] = ()
    uses: tuple[str, ...] = ()  # provider kinds called by the producer
    description: str = ""


class ArtifactRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ArtifactSpec] = {}

    def register(self, spec: ArtifactSpec) -> None:
        self._specs[spec.key] = spec

    def get(self, key: str) -> ArtifactSpec | None:
        return self._specs.get(key)

    def keys(self) -> list[str]:
        return sorted(self._specs)

    @classmethod
    def default(cls) -> ArtifactRegistry:
        reg = cls()
        for spec in BUILTIN_ARTIFACTS:
            reg.register(spec)
        return reg


class ArtifactStore:
    def __init__(
        self,
        registry: ArtifactRegistry,
        provider: Callable[[str], Any],
        events: EventBus | None = None,
        initial: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ):
        self.registry = registry
        self.provider = provider
        self.events = events or EventBus()
        self.options = options or {}
        self.timings: dict[str, float] = {}
        self._values: dict[str, Any] = dict(initial or {})

    def get(self, key: str) -> Any:
        if key in self._values:
            return self._values[key]
        spec = self.registry.get(key)
        if spec is None:
            raise PlanError(f"No producer for artifact {key!r}")
        for need in spec.needs:
            self.get(need)
        self.events.emit("stage_started", stage=key)
        t0 = time.perf_counter()
        value = spec.produce(self)
        self.timings[key] = time.perf_counter() - t0
        self.events.emit("stage_finished", stage=key, seconds=self.timings[key])
        self._values[key] = value
        return value

    def peek(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)


# --- built-in producers ---------------------------------------------------------------


def _samples(store: ArtifactStore):
    return audio.decode(store.get("audio").path)


def _transcript(store: ArtifactStore):
    transcript = store.provider("stt").transcribe(store.get("samples"), SAMPLE_RATE)
    if store.options.get("sentence_split", True):
        transcript = split_into_sentences(transcript)
    return transcript


def _expected_phonemes(store: ArtifactStore):
    words = sorted({normalize_word(w.text) for s in store.get("transcript").segments for w in s.words} - {""})
    return store.provider("g2p").pronounce(words)


def _heard_phonemes(store: ArtifactStore):
    samples = store.get("samples")
    recognizer = store.provider("phonemes")
    heard = []
    for seg in store.get("transcript").segments:
        chunk = audio.slice_seconds(samples, seg.start, seg.end, pad=SEGMENT_PAD_S)
        if not len(chunk):
            heard.append(PhoneSeq(phones=[], start=seg.start, end=seg.end))
            continue
        timed = recognizer.recognize_timed(chunk, SAMPLE_RATE)
        if timed is None:
            heard.append(PhoneSeq(recognizer.recognize(chunk, SAMPLE_RATE), seg.start, seg.end))
        else:
            offset = max(0.0, seg.start - SEGMENT_PAD_S)
            heard.append(PhoneSeq([p for p, _ in timed], seg.start, seg.end, [round(offset + t, 3) for _, t in timed]))
    return heard


BUILTIN_ARTIFACTS = [
    ArtifactSpec("samples", _samples, needs=("audio",), description="16 kHz mono float32 audio"),
    ArtifactSpec("transcript", _transcript, needs=("samples",), uses=("stt",),
                 description="sentences with word timestamps"),
    ArtifactSpec("expected_phonemes", _expected_phonemes, needs=("transcript",), uses=("g2p",),
                 description="accepted pronunciations of every transcript word"),
    ArtifactSpec("heard_phonemes", _heard_phonemes, needs=("transcript", "samples"), uses=("phonemes",),
                 description="phones actually heard, per sentence"),
]  # fmt: skip

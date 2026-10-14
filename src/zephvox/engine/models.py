"""Shared data model. Everything that crosses a plugin boundary is one of these types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

SAMPLE_RATE = 16_000

Verbatim = Literal["none", "partial", "full"]


@dataclass(frozen=True)
class AudioRef:
    path: Path
    sample_rate: int = SAMPLE_RATE


@dataclass
class Word:
    text: str
    start: float
    end: float
    confidence: float | None = None


@dataclass
class Segment:
    """One sentence (or sentence-like chunk) of speech."""

    text: str
    start: float
    end: float
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    segments: list[Segment]
    language: str = "en"
    provider: str = ""
    # How faithfully the STT keeps what was actually said (fillers, grammar errors).
    verbatim: Verbatim = "none"

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.segments)


@dataclass
class Pronunciation:
    """Accepted pronunciations of a word, each a list of canonical IPA phones."""

    word: str
    variants: list[list[str]]
    source: str = ""


@dataclass
class PhoneSeq:
    """Phones actually heard in one segment of audio."""

    phones: list[str]
    start: float = 0.0
    end: float = 0.0
    # When the recognizer knows them: when each phone was heard (absolute seconds).
    times: list[float] | None = None


@dataclass
class Finding:
    """One mistake, in the format every analyzer emits and every reporter consumes."""

    analyzer: str
    sentence: str
    target: str  # the word/phrase the finding is about
    said: str  # what the speaker produced
    expected: str  # what it should have been
    explanation: str
    category: str
    segment_index: int = 0
    word_span: tuple[int, int] | None = None
    time_span: tuple[float, float] | None = None
    confidence: float = 1.0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        data = dict(data)
        for key in ("word_span", "time_span"):
            if data.get(key) is not None:
                data[key] = tuple(data[key])
        return cls(**data)


@dataclass
class AnalysisResult:
    session_id: str
    audio_path: str
    sentences: list[str]
    findings: list[Finding]
    providers: dict[str, str] = field(default_factory=dict)
    analyzers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    duration: float = 0.0
    created: str = ""
    sentence_spans: list[tuple[float, float]] = field(default_factory=list)  # (start, end) per sentence

    def by_analyzer(self, name: str) -> list[Finding]:
        return [f for f in self.findings if f.analyzer == name]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["findings"] = [f.to_dict() for f in self.findings]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalysisResult:
        data = dict(data)
        data["findings"] = [Finding.from_dict(f) for f in data.get("findings", [])]
        data["sentence_spans"] = [tuple(s) for s in data.get("sentence_spans", [])]
        return cls(**data)

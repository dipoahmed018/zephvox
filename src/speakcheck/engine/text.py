"""Text helpers shared by producers and analyzers."""

from __future__ import annotations

import re

from .models import Segment, Transcript, Word

_EDGE_PUNCT = re.compile(r"^[^\w']+|[^\w']+$")
_SENTENCE_END = re.compile(r"[.?!][\"')\]]*$")


def clean_word(text: str) -> str:
    """Strip surrounding punctuation, keeping case and inner apostrophes ("Don't")."""
    text = text.replace("’", "'").strip()
    return _EDGE_PUNCT.sub("", text).strip("'")


def normalize_word(text: str) -> str:
    """Lookup key for a word: `clean_word` + lowercase."""
    return clean_word(text).lower()


def split_into_sentences(transcript: Transcript, max_words: int = 40) -> Transcript:
    """Re-cut segments at sentence punctuation, so every segment is one sentence.

    STT drivers chunk audio by time, not by sentence. Requires word timestamps; a transcript
    without words is returned unchanged.
    """
    words = [w for s in transcript.segments for w in s.words]
    if not words:
        return transcript

    segments: list[Segment] = []
    current: list[Word] = []

    def flush() -> None:
        if current:
            segments.append(
                Segment(
                    text=" ".join(w.text.strip() for w in current),
                    start=current[0].start,
                    end=current[-1].end,
                    words=list(current),
                )
            )
            current.clear()

    for word in words:
        if not word.text.strip():
            continue
        current.append(word)
        if _SENTENCE_END.search(word.text.strip()) or len(current) >= max_words:
            flush()
    flush()

    return Transcript(
        segments=segments,
        language=transcript.language,
        provider=transcript.provider,
        verbatim=transcript.verbatim,
    )


def transcript_from_text(text: str, duration: float) -> Transcript:
    """A transcript for speech whose text is already known (e.g. practice), as one segment.

    Word timings are spread evenly; analyzers align against the whole segment anyway.
    """
    tokens = text.split()
    step = duration / len(tokens) if tokens else 0.0
    words = [Word(t, i * step, (i + 1) * step) for i, t in enumerate(tokens)]
    segments = [Segment(text.strip(), 0.0, duration, words)] if tokens else []
    return Transcript(segments, provider="reference-text", verbatim="full")

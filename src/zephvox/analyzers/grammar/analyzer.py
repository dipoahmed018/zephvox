"""Grammar: ask an LLM for mistakes in each sentence, then keep only verifiable ones."""

from __future__ import annotations

import re
from typing import Any

from ...engine.errors import LLMError
from ...engine.models import Finding, Segment
from ...engine.text import normalize_word
from ..base import AnalysisContext, Analyzer, AnalyzerSettings
from .prompt import CATEGORIES, RESPONSE_SCHEMA, SYSTEM_PROMPT, user_prompt


def _locate(segment: Segment, phrase: str) -> tuple[int, int] | None:
    """Word indices of `phrase` inside the segment's words, if it lines up with them."""
    target = [normalize_word(t) for t in phrase.split()]
    words = [normalize_word(w.text) for w in segment.words]
    for i in range(len(words) - len(target) + 1):
        if target and words[i : i + len(target)] == target:
            return i, i + len(target) - 1
    return None


CONTRACTIONS = {
    "it's": "it is", "that's": "that is", "there's": "there is", "what's": "what is", "he's": "he is",
    "she's": "she is", "i'm": "i am", "you're": "you are", "we're": "we are", "they're": "they are",
    "i've": "i have", "you've": "you have", "we've": "we have", "they've": "they have", "i'll": "i will",
    "you'll": "you will", "we'll": "we will", "they'll": "they will", "i'd": "i would", "don't": "do not",
    "doesn't": "does not", "didn't": "did not", "can't": "cannot", "won't": "will not", "isn't": "is not",
    "aren't": "are not", "wasn't": "was not", "weren't": "were not", "let's": "let us",
    "gonna": "going to", "wanna": "want to", "gotta": "got to", "kinda": "kind of",
}  # fmt: skip


def _letters(text: str) -> str:
    """Words only: lowercase, no punctuation, contractions expanded — so that punctuation,
    capitalization or contraction-only 'fixes' (never mistakes in speech) compare equal."""
    words = re.sub(r"[^\w\s']", " ", text.replace("\u2019", "'").lower()).split()
    return " ".join(CONTRACTIONS.get(w, w) for w in words)


def _contains(sentence: str, phrase: str) -> bool:
    squash = lambda s: re.sub(r"\s+", " ", s.replace("’", "'")).strip().lower()  # noqa: E731
    return squash(phrase) in squash(sentence)


class GrammarAnalyzer(Analyzer):
    name = "grammar"
    needs = ("transcript",)
    uses = ("llm",)

    class Settings(AnalyzerSettings):
        batch_size: int = 5
        # High on purpose: in casual speech a missed nitpick is better than a false alarm.
        min_confidence: float = 0.85
        retries: int = 1

    def analyze(self, ctx: AnalysisContext) -> list[Finding]:
        transcript = ctx.get("transcript")
        if transcript.verbatim == "none":
            ctx.warn(
                f"The {transcript.provider or 'speech-to-text'} driver may silently fix grammar while "
                "transcribing, so some grammar mistakes can be missed."
            )
        llm = ctx.provider("llm")
        segments = transcript.segments
        findings: list[Finding] = []
        size = max(1, self.settings.batch_size)
        for start in range(0, len(segments), size):
            batch = segments[start : start + size]
            reply = self._ask(ctx, llm, [s.text for s in batch])
            if reply is not None:
                findings.extend(self._to_findings(ctx, reply, batch, start))
            done = min(start + size, len(segments))
            ctx.progress(f"sentences {done}/{len(segments)}", done / len(segments))
        return findings

    def _ask(self, ctx: AnalysisContext, llm: Any, sentences: list[str]) -> dict[str, Any] | None:
        for attempt in range(self.settings.retries + 1):
            try:
                return llm.complete_json(SYSTEM_PROMPT, user_prompt(sentences), RESPONSE_SCHEMA)
            except LLMError as e:
                if attempt == self.settings.retries:
                    ctx.warn(f"Grammar check skipped {len(sentences)} sentence(s): {e}")
        return None

    def _to_findings(self, ctx: AnalysisContext, reply: dict[str, Any],
                     batch: list[Segment], offset: int) -> list[Finding]:  # fmt: skip
        findings = []
        mistakes = reply.get("mistakes")
        if not isinstance(mistakes, list):
            ctx.warn("Grammar check returned no 'mistakes' list; ignoring the reply")
            return []
        dropped = 0
        for m in mistakes:
            try:
                index = int(m["index"])
                original = str(m["original"]).strip()
                correction = str(m["correction"]).strip()
                confidence = float(m.get("confidence", 1.0))
            except (KeyError, TypeError, ValueError):
                dropped += 1
                continue
            valid = (
                0 <= index < len(batch)
                and original
                and _letters(original) != _letters(correction)  # punctuation/contractions aren't mistakes
                and _contains(batch[index].text, original)  # guards against invented quotes
            )
            if not valid:
                dropped += 1
                continue
            if confidence < self.settings.min_confidence:
                continue
            segment = batch[index]
            span = _locate(segment, original)
            category = m.get("category") if m.get("category") in CATEGORIES else "other"
            findings.append(
                Finding(
                    analyzer=self.name,
                    sentence=segment.text,
                    target=original,
                    said=original,
                    expected=correction,
                    explanation=str(m.get("explanation", "")).strip(),
                    category=category,
                    segment_index=offset + index,
                    word_span=span,
                    time_span=(segment.words[span[0]].start, segment.words[span[1]].end) if span else None,
                    confidence=round(min(1.0, max(0.0, confidence)), 2),
                )
            )
        if dropped:
            ctx.warn(f"Ignored {dropped} grammar suggestion(s) that didn't match the transcript")
        return findings

"""Pronunciation: compare the phones expected for each word with the phones actually heard."""

from __future__ import annotations

from ...engine.models import Finding, Pronunciation, Segment
from ...engine.text import clean_word, normalize_word
from ..base import AnalysisContext, Analyzer, AnalyzerSettings
from .align import AlignOp, align
from .hints import category, errors_of, explain

# Short, usually-reduced words: judging them produces noise, not useful feedback.
FUNCTION_WORDS = frozenset("""
a an the to of and or but in on at for is are was were be been am i you he she it we they me him her us
them my your his its our their as by with from that this than then so do does did have has had not can will
would could should um uh uhm umm hmm oh ah like yeah okay ok
""".split())


def heard_per_word(segment: Segment, heard: list[str], expected: dict[str, Pronunciation]) -> dict[int, list[str]]:
    """Align the whole sentence once, then split the heard phones between its words."""
    ref: list[str] = []
    owner: list[int] = []
    for wi, word in enumerate(segment.words):
        p = expected.get(normalize_word(word.text))
        if p and p.variants:
            ref.extend(p.variants[0])
            owner.extend([wi] * len(p.variants[0]))

    per_word: dict[int, list[str]] = {wi: [] for wi in range(len(segment.words))}
    if not ref:
        return per_word
    _, ops = align(ref, heard)

    # Insertions belong to a word only when they fall *inside* it; ones at word
    # boundaries are usually segmentation noise.
    next_ref: list[int | None] = [None] * len(ops)
    upcoming = None
    for k in range(len(ops) - 1, -1, -1):
        next_ref[k] = upcoming
        if ops[k].ref_index is not None:
            upcoming = ops[k].ref_index
    prev = None
    for k, op in enumerate(ops):
        if op.ref_index is not None:
            prev = op.ref_index
            if op.heard is not None:
                per_word[owner[op.ref_index]].append(op.heard)
        elif prev is not None and next_ref[k] is not None and owner[prev] == owner[next_ref[k]]:
            per_word[owner[prev]].append(op.heard)
    return per_word


def best_variant(variants: list[list[str]], said: list[str]) -> tuple[float, list[str], list[AlignOp]]:
    """Score `said` against every accepted pronunciation; keep the closest.

    Returns (error cost per expected phone, that variant, its alignment).
    """
    return min(
        ((cost / len(v), v, ops) for v in variants for cost, ops in [align(v, said)]),
        key=lambda t: t[0],
    )


def has_major_error(ops: list[AlignOp]) -> bool:
    """A full substitution or a missing sound (e.g. θ→s) — clear mistakes in any word."""
    return any(o.op in ("sub", "del") and o.cost >= 1.0 for o in ops)


class PronunciationAnalyzer(Analyzer):
    name = "pronunciation"
    needs = ("transcript", "expected_phonemes", "heard_phonemes")

    class Settings(AnalyzerSettings):
        # Error cost per expected phone at or above which a word is flagged (0 = perfect).
        threshold: float = 0.3
        # Also flag any word with a full substitution or missing sound (e.g. θ→s), however
        # long the word is — averaging would otherwise hide it in longer words.
        flag_major_errors: bool = True
        min_phones: int = 2
        skip_words: list[str] = sorted(FUNCTION_WORDS)

    def analyze(self, ctx: AnalysisContext) -> list[Finding]:
        transcript = ctx.get("transcript")
        expected: dict[str, Pronunciation] = ctx.get("expected_phonemes")
        heard = ctx.get("heard_phonemes")

        findings: list[Finding] = []
        total = len(transcript.segments)
        for index, (segment, phones) in enumerate(zip(transcript.segments, heard, strict=True)):
            findings.extend(self._analyze_segment(index, segment, phones.phones, expected))
            ctx.progress(f"sentence {index + 1}/{total}", (index + 1) / total)

        unknown = sorted(w for w, p in expected.items() if not p.variants)
        if unknown:
            more = f" and {len(unknown) - 10} more" if len(unknown) > 10 else ""
            ctx.warn(f"No pronunciation known for: {', '.join(unknown[:10])}{more} (not checked)")
        return findings

    def _analyze_segment(self, index: int, segment: Segment, heard: list[str],
                         expected: dict[str, Pronunciation]) -> list[Finding]:  # fmt: skip
        per_word = heard_per_word(segment, heard, expected)
        skip = set(self.settings.skip_words)
        findings = []
        for wi, word in enumerate(segment.words):
            key = normalize_word(word.text)
            p = expected.get(key)
            if not p or not p.variants or key in skip or len(p.variants[0]) < self.settings.min_phones:
                continue
            said = per_word[wi]
            # Accept whichever valid pronunciation the speaker came closest to.
            score, variant, ops = best_variant(p.variants, said)
            major = self.settings.flag_major_errors and has_major_error(ops)
            if score < self.settings.threshold and not major:
                continue
            findings.append(
                Finding(
                    analyzer=self.name,
                    sentence=segment.text,
                    target=clean_word(word.text),
                    said=f"/{' '.join(said)}/" if said else "(not heard)",
                    expected=f"/{' '.join(variant)}/",
                    explanation=explain(ops) if said else "This word was not heard clearly.",
                    category=category(ops) if said else "unclear",
                    segment_index=index,
                    word_span=(wi, wi),
                    time_span=(word.start, word.end),
                    confidence=round(min(1.0, score), 2),
                    details={
                        "score": round(score, 3),
                        "errors": [{"type": o.op, "expected": o.expected, "heard": o.heard} for o in errors_of(ops)],
                        "accepted": [" ".join(v) for v in p.variants],
                        "stt_confidence": word.confidence,
                    },
                )
            )
        return findings

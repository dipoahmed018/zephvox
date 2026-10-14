"""Pronunciation: compare the phones expected for each word with the phones actually heard."""

from __future__ import annotations

from dataclasses import replace

from ...engine.models import Finding, Pronunciation, Segment
from ...engine.phonemes import is_vowel
from ...engine.text import clean_word, normalize_word
from ..base import AnalysisContext, Analyzer, AnalyzerSettings
from .align import AlignOp, align
from .hints import category, errors_of, explain

# Short, usually-reduced words: judging them produces noise, not useful feedback.
FUNCTION_WORDS = frozenset("""
a an the to of and or but in on at for is are was were be been am i you he she it we they me him her us
them my your his its our their as by with from that this than then so do does did have has had not can will
would could should um uh uhm umm hmm oh ah like yeah okay ok
i'm i'll i've i'd it's that's there's he's she's we're they're you're we've they've you've don't
doesn't didn't can't won't isn't aren't wasn't let's what's
""".split())

# Pairing an expected phone with a heard phone further than this outside its word's
# timestamps is penalised; STT word boundaries are approximate, so it's a soft anchor.
TIME_WINDOW_S = 0.3
TIME_PENALTY = 3.0  # > deletion + insertion, so distant pairings are never chosen

STOPS = frozenset("p t k b d ɡ".split())
NON_RHOTIC_PAIRS = {frozenset(p) for p in [("ɚ", "ə"), ("ɚ", "ʌ"), ("ɚ", "ɑ"), ("ɚ", "ɔ")]}


def _accent_relief(op: AlignOp, variant: list[str], relax_final_stops: bool, non_rhotic: bool) -> AlignOp:
    """Lower the cost of differences that are normal speech/accent variation, not mistakes."""
    i = op.ref_index
    if op.op == "del" and i is not None:
        is_final = i == len(variant) - 1
        if relax_final_stops and is_final and op.expected in STOPS:
            return replace(op, cost=0.5)  # "boo(k)": unreleased final stop
        if non_rhotic and op.expected == "ɹ" and (is_final or not is_vowel(variant[i + 1])):
            return replace(op, cost=0.0)  # "ca(r)", "pa(r)t": British-style r-dropping
    if non_rhotic and op.op == "sub" and frozenset((op.expected, op.heard)) in NON_RHOTIC_PAIRS:
        return replace(op, cost=0.0)  # "her" as /hə/
    return op


def heard_per_word(segment: Segment, heard: list[str], expected: dict[str, Pronunciation],
                   times: list[float] | None = None) -> dict[int, list[str]]:  # fmt: skip
    """Align the whole sentence once, then split the heard phones between its words.

    With `times` (when each phone was heard), the alignment is anchored to the word
    timestamps so it can't drift across long sentences.
    """
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
    penalty = None
    if times is not None:
        words = segment.words

        def penalty(i: int, j: int) -> float:
            w = words[owner[i]]
            inside = w.start - TIME_WINDOW_S <= times[j] <= w.end + TIME_WINDOW_S
            return 0.0 if inside else TIME_PENALTY

    _, ops = align(ref, heard, penalty=penalty)

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


def best_variant(variants: list[list[str]], said: list[str], relax_final_stops: bool = False,
                 non_rhotic: bool = False) -> tuple[float, list[str], list[AlignOp]]:  # fmt: skip
    """Score `said` against every accepted pronunciation; keep the closest.

    Returns (error cost per expected phone, that variant, its alignment). Optional leniency:
    `relax_final_stops` — a dropped word-final p/t/k/b/d/g counts as half an error;
    `non_rhotic` — r-dropping (British-style) isn't an error.
    """
    scored = []
    for v in variants:
        _, ops = align(v, said)
        if relax_final_stops or non_rhotic:
            ops = [_accent_relief(o, v, relax_final_stops, non_rhotic) for o in ops]
        scored.append((sum(o.cost for o in ops) / len(v), v, ops))
    return min(scored, key=lambda t: t[0])


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
        # Accept British-style r-dropping ("car" as /kɑ/) instead of flagging it against US English.
        accept_non_rhotic: bool = True
        min_phones: int = 2
        skip_words: list[str] = sorted(FUNCTION_WORDS)

    def analyze(self, ctx: AnalysisContext) -> list[Finding]:
        transcript = ctx.get("transcript")
        expected: dict[str, Pronunciation] = ctx.get("expected_phonemes")
        heard = ctx.get("heard_phonemes")

        findings: list[Finding] = []
        total = len(transcript.segments)
        for index, (segment, phones) in enumerate(zip(transcript.segments, heard, strict=True)):
            findings.extend(self._analyze_segment(index, segment, phones.phones, expected, phones.times))
            ctx.progress(f"sentence {index + 1}/{total}", (index + 1) / total)

        unknown = sorted(w for w, p in expected.items() if not p.variants)
        if unknown:
            more = f" and {len(unknown) - 10} more" if len(unknown) > 10 else ""
            ctx.warn(f"No pronunciation known for: {', '.join(unknown[:10])}{more} (not checked)")
        return findings

    def _analyze_segment(self, index: int, segment: Segment, heard: list[str],
                         expected: dict[str, Pronunciation], times: list[float] | None = None) -> list[Finding]:  # fmt: skip
        per_word = heard_per_word(segment, heard, expected, times)
        skip = set(self.settings.skip_words)
        findings = []
        for wi, word in enumerate(segment.words):
            key = normalize_word(word.text)
            p = expected.get(key)
            if not p or not p.variants or key in skip or len(p.variants[0]) < self.settings.min_phones:
                continue
            said = per_word[wi]
            # Accept whichever valid pronunciation the speaker came closest to.
            score, variant, ops = best_variant(p.variants, said, relax_final_stops=True,
                                               non_rhotic=self.settings.accept_non_rhotic)  # fmt: skip
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

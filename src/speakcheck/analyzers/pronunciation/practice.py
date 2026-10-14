"""Practice: score an attempt at saying a known word or sentence, sound by sound."""

from __future__ import annotations

from ...engine.models import Finding, Pronunciation
from ...engine.text import clean_word, normalize_word
from ..base import AnalysisContext, Analyzer, AnalyzerSettings
from .align import AlignOp
from .analyzer import best_variant, has_major_error, heard_per_word
from .hints import category, explain, tip


def phone_status(op: AlignOp) -> str:
    if op.op == "match":
        return "ok"
    if op.op == "ins":
        return "extra"
    if op.cost < 0.5:
        return "minor"  # accent-level difference, not a mistake
    return "missing" if op.op == "del" else "wrong"


class PracticeAnalyzer(Analyzer):
    """Emits one finding per target word, always — practice wants feedback on correct words too."""

    name = "practice"
    needs = ("transcript", "expected_phonemes", "heard_phonemes")

    class Settings(AnalyzerSettings):
        pass_score: int = 85
        different_word_score: int = 30

    def analyze(self, ctx: AnalysisContext) -> list[Finding]:
        transcript = ctx.get("transcript")
        expected: dict[str, Pronunciation] = ctx.get("expected_phonemes")
        heard = ctx.get("heard_phonemes")
        findings = []
        for index, (segment, phones) in enumerate(zip(transcript.segments, heard, strict=True)):
            per_word = heard_per_word(segment, phones.phones, expected)
            nothing_heard = not phones.phones
            for wi, word in enumerate(segment.words):
                p = expected.get(normalize_word(word.text))
                if not p or not p.variants:
                    ctx.warn(f"No pronunciation known for {clean_word(word.text)!r}; it can't be scored")
                    continue
                findings.append(self._score_word(index, segment.text, wi, word, p, per_word[wi], nothing_heard))
        return findings

    def _score_word(self, index, sentence, wi, word, p: Pronunciation, said: list[str], nothing_heard: bool):
        cost, variant, ops = best_variant(p.variants, said)
        score = 0 if nothing_heard else round(100 * max(0.0, 1.0 - cost))
        if nothing_heard:
            status = "no_speech"
        elif score < self.settings.different_word_score:
            status = "different_word"
        else:
            status = "ok"
        passed = status == "ok" and score >= self.settings.pass_score and not has_major_error(ops)
        if status == "no_speech":
            explanation = "I didn't hear anything — try again a little louder or closer to the microphone."
        elif status == "different_word":
            explanation = "That sounded like a different word. Listen to the example and try again."
        elif passed:
            explanation = "Well done!"
        else:
            explanation = explain(ops)
        return Finding(
            analyzer=self.name,
            sentence=sentence,
            target=clean_word(word.text),
            said=f"/{' '.join(said)}/" if said else "(not heard)",
            expected=f"/{' '.join(variant)}/",
            explanation=explanation,
            category="ok" if passed else category(ops),
            segment_index=index,
            word_span=(wi, wi),
            time_span=(word.start, word.end),
            details={
                "score": score,
                "passed": passed,
                "status": status,
                "phones": [{"expected": o.expected, "heard": o.heard, "status": phone_status(o)} for o in ops],
                "tip": "" if passed else tip(ops),
                "accepted": [" ".join(v) for v in p.variants],
            },
        )

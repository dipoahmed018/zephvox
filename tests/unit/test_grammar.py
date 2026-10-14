import pytest

from speakcheck.analyzers.base import AnalysisContext
from speakcheck.analyzers.grammar.analyzer import GrammarAnalyzer
from speakcheck.analyzers.grammar.prompt import RESPONSE_SCHEMA, user_prompt
from speakcheck.engine.errors import LLMError
from speakcheck.engine.models import Segment, Transcript, Word


def _transcript(*sentences, verbatim="partial"):
    segs, t = [], 0.0
    for s in sentences:
        words = []
        for token in s.split():
            words.append(Word(token, t, t + 0.3))
            t += 0.3
        segs.append(Segment(s, words[0].start, words[-1].end, words))
    return Transcript(segs, provider="stt", verbatim=verbatim)


class ScriptedLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def complete_json(self, system, user, schema):
        self.calls.append(user)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _run(transcript, llm, **settings):
    warnings, progress = [], []
    ctx = AnalysisContext({"transcript": transcript}.__getitem__, {"llm": llm}.__getitem__, warnings.append,
                          lambda m, f: progress.append(f))  # fmt: skip
    return GrammarAnalyzer(settings).analyze(ctx), warnings, progress


def mistake(index=0, original="he go", correction="he went", **kw):
    return {"index": index, "original": original, "correction": correction, "category": "verb-tense",
            "explanation": "Past tense.", "confidence": 0.9, **kw}  # fmt: skip


def test_valid_mistake_becomes_finding():
    t = _transcript("Yesterday he go to market.")
    findings, warnings, progress = _run(t, ScriptedLLM({"mistakes": [mistake()]}))
    (f,) = findings
    assert (f.target, f.said, f.expected, f.category) == ("he go", "he go", "he went", "verb-tense")
    assert f.word_span == (1, 2) and f.time_span == pytest.approx((0.3, 0.9))
    assert f.sentence == "Yesterday he go to market."
    assert warnings == [] and progress == [1.0]


def test_hallucinated_and_malformed_suggestions_are_dropped():
    t = _transcript("I am agree with you.")
    reply = {"mistakes": [
        mistake(original="she were", correction="she was"),  # not in sentence
        mistake(index=5, original="am agree", correction="agree"),  # bad index
        mistake(original="agree", correction="agree"),  # no change
        mistake(original="am agree", correction="Am agree,"),  # punctuation/capitals only
        mistake(original="I am", correction="I'm"),  # contraction only
        {"index": "x"},  # malformed
        mistake(original="am agree", correction="agree", category="nonsense"),
    ]}  # fmt: skip
    findings, warnings, _ = _run(t, ScriptedLLM(reply))
    assert [(f.said, f.expected, f.category) for f in findings] == [("am agree", "agree", "other")]
    assert "Ignored 6" in warnings[0]


def test_low_confidence_is_filtered_silently():
    t = _transcript("He go home.")
    findings, warnings, _ = _run(t, ScriptedLLM({"mistakes": [mistake(confidence=0.2)]}))
    assert findings == [] and warnings == []


def test_phrase_not_aligned_with_words_has_no_span():
    t = _transcript("Yesterday he go, to market.")
    findings, _, _ = _run(t, ScriptedLLM({"mistakes": [mistake(original="go, to", correction="went to")]}))
    assert findings[0].word_span == (2, 3)
    findings, _, _ = _run(t, ScriptedLLM({"mistakes": [mistake(original="e go", correction="x")]}))
    assert findings[0].word_span is None and findings[0].time_span is None


def test_batches_and_offsets_segment_indices():
    t = _transcript("One fine.", "Two fine.", "He go now.")
    llm = ScriptedLLM({"mistakes": []}, {"mistakes": [mistake(index=0)]})
    findings, _, progress = _run(t, llm, batch_size=2)
    assert len(llm.calls) == 2
    assert findings[0].segment_index == 2
    assert progress == [pytest.approx(2 / 3), 1.0]


def test_llm_errors_are_retried_then_warned():
    t = _transcript("He go now.")
    findings, warnings, _ = _run(t, ScriptedLLM(LLMError("bad json"), {"mistakes": [mistake()]}))
    assert len(findings) == 1 and warnings == []
    findings, warnings, _ = _run(t, ScriptedLLM(LLMError("down"), LLMError("down")))
    assert findings == [] and "skipped 1 sentence" in warnings[0]


def test_reply_without_mistakes_list():
    findings, warnings, _ = _run(_transcript("Hi."), ScriptedLLM({"oops": 1}))
    assert findings == [] and "no 'mistakes' list" in warnings[0]


def test_warns_when_stt_is_not_verbatim():
    _, warnings, _ = _run(_transcript("Hi.", verbatim="none"), ScriptedLLM({"mistakes": []}))
    assert "silently fix grammar" in warnings[0]


def test_prompt_and_schema_shape():
    prompt = user_prompt(["Hello.", "He go."])
    assert prompt == "Sentences:\n0: Hello.\n1: He go."
    item = RESPONSE_SCHEMA["properties"]["mistakes"]["items"]
    assert set(item["required"]) == set(item["properties"])

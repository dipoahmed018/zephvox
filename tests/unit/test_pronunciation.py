from speakcheck.analyzers.base import AnalysisContext
from speakcheck.analyzers.pronunciation.align import align
from speakcheck.analyzers.pronunciation.analyzer import PronunciationAnalyzer
from speakcheck.analyzers.pronunciation.hints import category, describe, errors_of, explain
from speakcheck.engine.models import PhoneSeq, Pronunciation, Segment, Transcript, Word


class TestAlign:
    def test_identical(self):
        cost, ops = align(["θ", "ɪ", "ŋ", "k"], ["θ", "ɪ", "ŋ", "k"])
        assert cost == 0 and all(op.op == "match" for op in ops)

    def test_substitution(self):
        cost, ops = align(["θ", "ɪ", "ŋ", "k"], ["s", "ɪ", "ŋ", "k"])
        assert cost == 1.0
        assert ops[0].op == "sub" and (ops[0].expected, ops[0].heard) == ("θ", "s")

    def test_deletion_and_insertion(self):
        _, ops = align(["k", "æ", "t"], ["k", "æ"])
        assert [op.op for op in ops] == ["match", "match", "del"]
        cost, ops = align(["k", "æ", "t"], ["k", "æ", "t", "ə"])
        assert cost == 0.5 and ops[-1].op == "ins" and ops[-1].ref_index is None

    def test_empty_sides(self):
        assert align([], []) == (0.0, [])
        cost, ops = align(["a"], [])
        assert cost == 1.0 and ops[0].op == "del"
        cost, ops = align([], ["ə"])
        assert cost == 0.5 and ops[0].op == "ins"


class TestHints:
    def test_explain_and_category(self):
        _, ops = align(["θ", "ɪ", "ŋ", "k"], ["s", "ɪ", "ŋ"])
        assert category(ops) == "θ→s"
        text = explain(ops)
        assert "'s' as in see" in text and "'th' as in think" in text and "missing" in text

    def test_insertion_and_unknown_phone(self):
        _, ops = align(["s", "p", "iː"], ["ə", "s", "p", "iː"])
        assert category(ops) == "+ə"
        assert "extra" in explain(ops)
        assert describe("x") == "/x/"

    def test_deletion_category_and_no_errors(self):
        _, ops = align(["k", "æ", "t"], ["k", "æ"])
        assert category(ops) == "-t"
        _, ops = align(["k"], ["k"])
        assert errors_of(ops) == [] and category(ops) == "unclear"
        assert explain(ops) == "This word was not pronounced clearly."


def _ctx(transcript, expected, heard, warnings=None, progress=None):
    values = {"transcript": transcript, "expected_phonemes": expected, "heard_phonemes": heard}
    return AnalysisContext(values.__getitem__, lambda k: None, (warnings if warnings is not None else []).append,
                           (lambda m, f: progress.append(f)) if progress is not None else None)  # fmt: skip


def _single(words, lexicon, heard):
    seg = Segment(" ".join(w for w, _, _ in words), 0, 1, [Word(w, s, e) for w, s, e in words])
    expected = {k: Pronunciation(k, v) for k, v in lexicon.items()}
    return Transcript([seg]), expected, [PhoneSeq(heard)]


class TestPronunciationAnalyzer:
    def test_flags_th_to_s(self):
        t, exp, heard = _single([("I", 0, 0.2), ("think", 0.2, 0.6), ("so.", 0.6, 0.9)],
                                {"i": [["aɪ"]], "think": [["θ", "ɪ", "ŋ", "k"]], "so": [["s", "oʊ"]]},
                                ["aɪ", "s", "ɪ", "ŋ", "k", "s", "oʊ"])  # fmt: skip
        progress = []
        findings = PronunciationAnalyzer().analyze(_ctx(t, exp, heard, progress=progress))
        assert len(findings) == 1
        f = findings[0]
        assert (f.target, f.said, f.expected, f.category) == ("think", "/s ɪ ŋ k/", "/θ ɪ ŋ k/", "θ→s")
        assert f.word_span == (1, 1) and f.time_span == (0.2, 0.6)
        assert f.details["errors"] == [{"type": "sub", "expected": "θ", "heard": "s"}]
        assert progress == [1.0]

    def test_any_accepted_variant_passes(self):
        lexicon = {"either": [["i", "ð", "ɚ"], ["aɪ", "ð", "ɚ"]], "way": [["w", "eɪ"]]}
        t, exp, heard = _single([("either", 0, 0.4), ("way", 0.4, 0.7)], lexicon, ["aɪ", "ð", "ɚ", "w", "eɪ"])
        assert PronunciationAnalyzer().analyze(_ctx(t, exp, heard)) == []

    def test_minor_accent_differences_pass(self):
        # Schwa for /ʌ/ and a dropped schwa are not mistakes.
        lexicon = {"london": [["l", "ʌ", "n", "d", "ə", "n"]]}
        t, exp, heard = _single([("London", 0, 0.5)], lexicon, ["l", "ə", "n", "d", "n"])
        assert PronunciationAnalyzer().analyze(_ctx(t, exp, heard)) == []

    def test_skips_function_and_short_and_unknown_words(self):
        lexicon = {"the": [["ð", "ə"]], "ox": [["ɑ", "k", "s"]], "a": [["ə"]]}
        t, exp, heard = _single([("the", 0, 0.1), ("a", 0.1, 0.2), ("Zork", 0.2, 0.5), ("ox", 0.5, 0.8)],
                                {**lexicon, "zork": []}, ["d", "ə", "ə", "z", "ɔ", "ɹ", "k", "ɑ", "k", "s"])  # fmt: skip
        warnings = []
        findings = PronunciationAnalyzer({"min_phones": 4}).analyze(_ctx(t, exp, heard, warnings))
        assert findings == []
        assert "zork" in warnings[0]

    def test_word_not_heard(self):
        lexicon = {"very": [["v", "ɛ", "ɹ", "i"]], "good": [["ɡ", "ʊ", "d"]]}
        t, exp, heard = _single([("very", 0, 0.3), ("good", 0.3, 0.6)], lexicon, ["ɡ", "ʊ", "d"])
        (f,) = PronunciationAnalyzer().analyze(_ctx(t, exp, heard))
        assert (f.target, f.said, f.category) == ("very", "(not heard)", "unclear")

    def test_interior_insertions_count_boundary_ones_do_not(self):
        lexicon = {"sport": [["s", "p", "ɔ", "ɹ", "t"]], "is": [["ɪ", "z"]], "fun": [["f", "ʌ", "n"]]}
        # "esport" (extra vowel before the word) at a boundary is not blamed; "fuhun" inside is.
        heard = ["ɛ", "s", "p", "ɔ", "ɹ", "t", "ɪ", "z", "f", "ʌ", "h", "ʌ", "n"]
        t, exp, h = _single([("sport", 0, 0.4), ("is", 0.4, 0.5), ("fun", 0.5, 0.8)], lexicon, heard)
        findings = PronunciationAnalyzer({"threshold": 0.3}).analyze(_ctx(t, exp, h))
        assert [f.target for f in findings] == ["fun"]
        assert findings[0].category.startswith("+")

    def test_no_known_words_in_sentence(self):
        t, exp, heard = _single([("Xyz", 0, 0.3)], {"xyz": []}, ["k"])
        assert PronunciationAnalyzer().analyze(_ctx(t, exp, heard)) == []

    def test_many_unknown_words_warning_is_truncated(self):
        words = [(f"w{i}", i, i + 1) for i in range(12)]
        t, exp, heard = _single(words, {f"w{i}": [] for i in range(12)}, [])
        warnings = []
        PronunciationAnalyzer().analyze(_ctx(t, exp, heard, warnings))
        assert "and 2 more" in warnings[0]

    def test_major_error_flagging_can_be_disabled(self):
        t, exp, heard = _single([("think", 0, 0.4)], {"think": [["θ", "ɪ", "ŋ", "k"]]}, ["s", "ɪ", "ŋ", "k"])
        assert len(PronunciationAnalyzer().analyze(_ctx(t, exp, heard))) == 1
        # Without it, one error in four phones (0.25) stays under the 0.3 threshold.
        assert PronunciationAnalyzer({"flag_major_errors": False}).analyze(_ctx(t, exp, heard)) == []

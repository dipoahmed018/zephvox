import wave

import numpy as np
import pytest

from speakcheck.engine import audio
from speakcheck.engine.errors import AudioError
from speakcheck.engine.events import EventBus
from speakcheck.engine.models import Segment, Transcript, Word
from speakcheck.engine.phonemes import (
    arpabet_to_ipa,
    deletion_cost,
    insertion_cost,
    is_vowel,
    normalize,
    normalize_phone,
    split_ipa,
    substitution_cost,
)
from speakcheck.engine.text import clean_word, normalize_word, split_into_sentences


class TestPhonemes:
    @pytest.mark.parametrize(
        "raw, canonical",
        [("iː", "i"), ("ˈæ", "æ"), ("ɐ", "ə"), ("ᵻ", "ɪ"), ("ɾ", "t"), ("ɜː", "ɚ"), ("g", "ɡ"), ("r", "ɹ"),
         ("n̩", "n"), ("əʊ", "oʊ"), ("a", "æ"), ("oː", "ɔ"), ("θ", "θ"), ("dʒ", "dʒ")],
    )  # fmt: skip
    def test_normalize_phone(self, raw, canonical):
        assert normalize_phone(raw) == canonical

    def test_normalize_drops_empty_and_word_separators(self):
        assert normalize(["h", "ˈ", "|", "ə", " "]) == ["h", "ə"]

    def test_arpabet_to_ipa(self):
        assert arpabet_to_ipa(["TH", "IH1", "NG", "K"]) == ["θ", "ɪ", "ŋ", "k"]
        assert arpabet_to_ipa(["AH0", "B", "AW1", "T"]) == ["ə", "b", "aʊ", "t"]
        assert arpabet_to_ipa(["K", "AH1", "P"]) == ["k", "ʌ", "p"]

    def test_split_ipa(self):
        assert split_ipa("tʃˈeɪndʒ") == ["tʃ", "eɪ", "n", "dʒ"]
        assert split_ipa("kuːbɝniːts") == ["k", "u", "b", "ɚ", "n", "i", "t", "s"]
        assert split_ipa(["d", "ʒ", "a", "ɪ", "r", "o", "ʊ"]) == ["dʒ", "aɪ", "ɹ", "oʊ"]
        assert split_ipa("tɪk-tɑːk") == ["t", "ɪ", "k", "t", "ɑ", "k"]

    def test_arpabet_unknown_symbol(self):
        with pytest.raises(ValueError):
            arpabet_to_ipa(["QQ1"])

    def test_costs(self):
        assert is_vowel("oʊ") and not is_vowel("θ")
        assert substitution_cost("θ", "θ") == 0
        assert substitution_cost("ə", "ʌ") == 0.25
        assert substitution_cost("i", "ɪ") == 0.5
        assert substitution_cost("θ", "s") == 1.0
        assert substitution_cost("s", "z") == 0.5
        assert deletion_cost("ə") == 0.25 and deletion_cost("ɹ") == 1.0
        assert insertion_cost("ə") == 0.5


class TestText:
    def test_word_cleanup(self):
        assert clean_word("“Don’t,”") == "Don't"
        assert normalize_word("Market.") == "market"
        assert normalize_word("...") == ""

    def test_split_into_sentences(self):
        words = [Word("Hi", 0, 0.2), Word("there.", 0.2, 0.5), Word("How", 0.6, 0.8), Word("are", 0.8, 0.9),
                 Word(" ", 0.9, 0.9), Word("you?", 0.9, 1.2), Word("Fine", 1.3, 1.5)]  # fmt: skip
        t = split_into_sentences(Transcript([Segment("x", 0, 1.5, words)], provider="p", verbatim="partial"))
        assert [s.text for s in t.segments] == ["Hi there.", "How are you?", "Fine"]
        assert (t.segments[1].start, t.segments[1].end) == (0.6, 1.2)
        assert t.provider == "p" and t.verbatim == "partial"

    def test_split_caps_long_sentences(self):
        words = [Word("w", i, i + 1) for i in range(5)]
        t = split_into_sentences(Transcript([Segment("x", 0, 5, words)]), max_words=2)
        assert [len(s.words) for s in t.segments] == [2, 2, 1]

    def test_split_without_words_is_noop(self):
        t = Transcript([Segment("Hello.", 0, 1)])
        assert split_into_sentences(t) is t


class TestAudio:
    def test_roundtrip(self, tmp_path):
        path = tmp_path / "a.wav"
        samples = np.sin(np.linspace(0, 100, 16000)).astype(np.float32) * 0.5
        audio.write_wav(path, samples)
        decoded = audio.decode(path)
        assert len(decoded) == 16000
        assert np.allclose(decoded, samples, atol=1e-3)
        assert audio.duration(decoded) == 1.0

    def test_slice_with_padding_is_clamped(self):
        samples = np.arange(16000, dtype=np.float32)
        assert len(audio.slice_seconds(samples, 0.0, 0.5, pad=0.1)) == 9600
        assert len(audio.slice_seconds(samples, 0.9, 2.0, pad=0.1)) == 3200

    def test_missing_file(self, tmp_path):
        with pytest.raises(AudioError, match="not found"):
            audio.decode(tmp_path / "nope.wav")

    def test_own_recordings_need_no_decoder(self, tmp_path, monkeypatch):
        path = tmp_path / "rec.wav"
        audio.write_wav(path, np.full(800, 0.25, dtype=np.float32))
        monkeypatch.setattr(audio.importlib.util, "find_spec", lambda _: None)
        monkeypatch.setattr(audio.shutil, "which", lambda _: None)
        assert np.allclose(audio.decode(path), 0.25, atol=1e-4)

    def test_other_files_are_resampled_to_mono(self, tmp_path):
        pytest.importorskip("av")
        path = tmp_path / "stereo44.wav"
        stereo = (np.full((44100, 2), 0.5) * 32767).astype("<i2")
        with wave.open(str(path), "wb") as f:
            f.setnchannels(2), f.setsampwidth(2), f.setframerate(44100)
            f.writeframes(stereo.tobytes())
        decoded = audio.decode(path)
        assert abs(len(decoded) - 16000) <= 16 and decoded.dtype == np.float32
        assert np.allclose(decoded[100:-100], 0.5 * np.sqrt(2), atol=1e-2)  # ffmpeg's downmix: each channel at -3 dB

    @pytest.mark.parametrize("backend", ["pyav", "ffmpeg"])
    def test_undecodable_file(self, tmp_path, monkeypatch, backend):
        if backend == "pyav":
            pytest.importorskip("av")
        else:
            if audio.shutil.which("ffmpeg") is None:
                pytest.skip("ffmpeg not installed")
            monkeypatch.setattr(audio.importlib.util, "find_spec", lambda _: None)
        bad = tmp_path / "bad.wav"
        bad.write_bytes(b"not audio")
        with pytest.raises(AudioError, match="(?i)could not decode"):
            audio.decode(bad)

    def test_needs_pyav_or_ffmpeg_for_other_files(self, tmp_path, monkeypatch):
        path = tmp_path / "talk.mp3"
        path.write_bytes(b"ID3")
        monkeypatch.setattr(audio.importlib.util, "find_spec", lambda _: None)
        monkeypatch.setattr(audio.shutil, "which", lambda _: None)
        with pytest.raises(AudioError, match="models extra, or ffmpeg"):
            audio.decode(path)


def test_event_bus_filters_and_unsubscribes():
    bus = EventBus()
    seen, only_b = [], []
    unsubscribe = bus.subscribe(seen.append)
    bus.subscribe(only_b.append, types=["b"])
    bus.emit("a", x=1)
    bus.emit("b")
    unsubscribe()
    bus.emit("a")
    assert [e.type for e in seen] == ["a", "b"]
    assert seen[0].data == {"x": 1}
    assert [e.type for e in only_b] == ["b"]


class TestSplitOnSilence:
    def test_short_audio_is_one_piece(self):
        samples = np.ones(16000 * 5, dtype=np.float32)
        (piece,) = audio.split_on_silence(samples)
        assert piece[0] == 0.0 and len(piece[1]) == len(samples)

    def test_cuts_at_the_quiet_gap(self):
        loud = np.full(16000 * 20, 0.5, dtype=np.float32)
        gap = np.zeros(16000 // 2, dtype=np.float32)
        samples = np.concatenate([loud, gap, loud, gap, loud])  # 61 s with gaps at 20 s and 40.5 s
        pieces = audio.split_on_silence(samples, max_seconds=28, min_seconds=10)
        starts = [round(p[0], 1) for p in pieces]
        assert len(pieces) == 3
        assert 20.0 <= starts[1] <= 20.5 and 40.5 <= starts[2] <= 41.0
        assert sum(len(p[1]) for p in pieces) == len(samples)  # nothing lost or duplicated
        assert all(len(p[1]) <= 28 * 16000 for p in pieces)

    def test_no_silence_still_respects_max_length(self):
        samples = np.full(16000 * 70, 0.5, dtype=np.float32)
        pieces = audio.split_on_silence(samples, max_seconds=28, min_seconds=10)
        assert all(len(p[1]) <= 28 * 16000 for p in pieces) and sum(len(p[1]) for p in pieces) == len(samples)

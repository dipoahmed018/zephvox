"""G2P pieces that need torch but no downloads: DeepPhonemizer inference, Kokoro's fallback."""

import json
import sys

import pytest

from zephvox.engine.models import Pronunciation
from zephvox.providers.base import Services
from zephvox.providers.g2p.deep_phonemizer import DeepPhonemizerG2P
from zephvox.providers.tts import kokoro


class TestDeepPhonemizer:
    def test_tokenizer(self):
        pytest.importorskip("torch")
        from zephvox.providers.g2p._deep_phonemizer import Tokenizer

        text = Tokenizer(list("abc"), ["de", "en_us"], char_repeats=2, lowercase=True)
        # 0 pad, 1 <de>, 2 <en_us>, 3 <end>, then a b c
        assert text.encode("Ab!", "en_us") == [2, 4, 4, 5, 5, 3]
        phonemes = Tokenizer(["x", "y"], ["en_us"])
        assert phonemes.decode([1, 3, 0, 4, 2, 3]) == ["x", "y"]  # stops at <end>, drops specials

    def test_tiny_random_model_end_to_end(self, tmp_path):
        torch = pytest.importorskip("torch")
        pytest.importorskip("safetensors")
        from safetensors.torch import save_file

        from zephvox.providers.g2p._deep_phonemizer import ForwardTransformer

        config = {"model": {"d_model": 8, "d_fft": 16, "layers": 1, "heads": 2},
                  "preprocessing": {"languages": ["en_us"], "text_symbols": list("abcdefghijklmnopqrstuvwxyz'"),
                                    "phoneme_symbols": list("abdɪ"), "char_repeats": 3, "lowercase": True}}  # fmt: skip
        (tmp_path / "config.json").write_text(json.dumps(config))
        torch.manual_seed(0)
        model = ForwardTransformer(1 + 1 + 1 + 27, 1 + 1 + 1 + 4, 8, 16, 1, 2)
        save_file({k: v.half() for k, v in model.state_dict().items()}, tmp_path / "model.safetensors")

        g2p = DeepPhonemizerG2P({"model": str(tmp_path)})
        assert g2p.check_available().ok and g2p.downloads() == []  # local folder: nothing to fetch
        out = g2p.pronounce(["hello", "123"])
        assert set(out) == {"hello", "123"}
        assert out["123"].variants == []  # no letters the model knows
        assert all(p in {"a", "b", "d", "ɪ"} for v in out["hello"].variants for p in v)

    def test_downloads_from_hugging_face(self):
        (d,) = DeepPhonemizerG2P({"model": "someone/g2p", "revision": None}).downloads()
        assert (d.source, d.name, d.patterns) == ("huggingface", "someone/g2p", ("config.json", "model.safetensors"))
        assert d.revision is None
        assert DeepPhonemizerG2P().downloads()[0].revision  # the default is pinned to one upload


class FakeG2P:
    def check_available(self):
        return type("A", (), {"ok": True})()

    def pronounce(self, words):
        table = {"Ollama": [["ɑ", "l", "ɑ", "m", "ə"]], "Kubernetes": [["k", "u", "b", "ɚ", "n", "eɪ", "tʃ"]]}
        return {w: Pronunciation(w, table.get(w, []), "fake") for w in words}


class TestKokoroWithoutEspeak:
    def test_unknown_words_in_misaki_spelling(self):
        fallback = kokoro.UnknownWords(FakeG2P())
        token = type("Token", (), {"text": "Kubernetes"})()
        assert fallback(token) == ("kubəɹnAʧ", 1)
        assert fallback(type("Token", (), {"text": "qwzxv"})()) == (None, None)

    def test_fallback_needs_the_driver(self):
        assert kokoro.KokoroTTS()._fallback() is None  # no engine to build it
        tts = kokoro.KokoroTTS(services=Services(build=lambda kind, name: FakeG2P()))
        assert isinstance(tts._fallback(), kokoro.UnknownWords)

    def test_stand_in_for_espeak(self, monkeypatch):
        pytest.importorskip("misaki")
        monkeypatch.delitem(sys.modules, "misaki.espeak", raising=False)
        kokoro.stand_in_for_espeak()
        from misaki import espeak

        with pytest.raises(RuntimeError):
            espeak.EspeakFallback(british=False)
        assert "phonemizer" not in sys.modules

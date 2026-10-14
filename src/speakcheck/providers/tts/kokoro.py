"""Natural reference voices with Kokoro-82M (https://huggingface.co/hexgrad/Kokoro-82M).

Kokoro reads words from misaki's dictionaries. For words they lack, it would ask espeak-ng (GPL),
which speakcheck doesn't install: the `deep-phonemizer` G2P driver answers instead.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import types
import warnings
from typing import Any

import numpy as np

from ...engine.errors import SpeakcheckError
from ..base import Availability, Download, ProviderSettings, TTSProvider

SAMPLE_RATE = 24_000

# id → (label, accent). The first letter of the id is Kokoro's language code (a = US, b = UK).
VOICES = {
    "af_heart": ("Heart — American, female", "en-us"),
    "af_bella": ("Bella — American, female", "en-us"),
    "af_nicole": ("Nicole — American, female, soft", "en-us"),
    "am_michael": ("Michael — American, male", "en-us"),
    "am_fenrir": ("Fenrir — American, male", "en-us"),
    "bf_emma": ("Emma — British, female", "en-gb"),
    "bf_isabella": ("Isabella — British, female", "en-gb"),
    "bm_george": ("George — British, male", "en-gb"),
    "bm_fable": ("Fable — British, male", "en-gb"),
}


class KokoroTTS(TTSProvider):
    name = "kokoro"

    class Settings(ProviderSettings):
        voice: str = "af_heart"
        speed: float = 0.9  # a little slower than normal helps learners hear each sound
        # CPU by default: Kokoro is faster than real time there, and its LSTM layers fail on
        # some ROCm GPUs. It also leaves the GPU to speech recognition and the LLM.
        device: str = "cpu"
        repo_id: str = "hexgrad/Kokoro-82M"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._pipelines: dict[str, Any] = {}

    def downloads(self) -> list[Download]:
        patterns = ("config.json", "kokoro-v1_0.pth", f"voices/{self.settings.voice}.pt")
        return [Download("huggingface", self.settings.repo_id, 0.33, patterns)]

    def check_available(self) -> Availability:
        if importlib.util.find_spec("kokoro") is None:
            return Availability(False, "python package 'kokoro' not installed (uv sync --extra voice)")
        if self.settings.voice not in VOICES:
            return Availability(False, f"unknown voice {self.settings.voice!r}")
        return Availability(True)

    def capabilities(self) -> dict[str, Any]:
        return {
            "voice": self.settings.voice,
            "voices": [{"id": v, "label": label, "accent": accent} for v, (label, accent) in VOICES.items()],
            "format": "wav",
        }

    def _pipeline(self, lang: str):
        if lang not in self._pipelines:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                stand_in_for_espeak()
                from kokoro import KPipeline

                pipeline = KPipeline(lang_code=lang, repo_id=self.settings.repo_id, device=self.settings.device)
                if (fallback := self._fallback()) is not None:
                    pipeline.g2p.fallback = fallback
                self._pipelines[lang] = pipeline
        return self._pipelines[lang]

    def _fallback(self) -> UnknownWords | None:
        if self.services.build is None:
            return None
        try:
            g2p = self.services.build("g2p", "deep-phonemizer")
        except Exception:
            return None
        return UnknownWords(g2p) if g2p.check_available().ok else None

    def synthesize(self, text: str) -> bytes:
        voice = self.settings.voice
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pieces = [r.audio.numpy() for r in self._pipeline(voice[0])(text, voice=voice, speed=self.settings.speed)
                          if r.audio is not None]  # fmt: skip
        except Exception as e:  # model download/runtime problems → let the caller fall back
            raise SpeakcheckError(f"Kokoro failed: {e}") from e
        if not pieces:
            raise SpeakcheckError("Kokoro produced no audio")
        return wav_bytes(np.concatenate(pieces), SAMPLE_RATE)

    def close(self) -> None:
        self._pipelines.clear()


def stand_in_for_espeak() -> None:
    """Kokoro imports misaki.espeak, which needs the GPL espeak packages: give it an empty module.

    Kokoro then starts without its espeak fallback (it catches the error below), and `_pipeline`
    plugs in `UnknownWords`.
    """
    if "misaki.espeak" in sys.modules:
        return
    module = types.ModuleType("misaki.espeak")

    class EspeakFallback:
        def __init__(self, *args: Any, **kwargs: Any):
            raise RuntimeError("espeak is not used by speakcheck")

    module.EspeakFallback = module.EspeakG2P = EspeakFallback  # type: ignore[attr-defined]
    sys.modules["misaki.espeak"] = module
    import misaki

    misaki.espeak = module  # type: ignore[attr-defined]


# canonical phones → misaki's one-letter spellings (US)
TO_MISAKI = {"aɪ": "I", "aʊ": "W", "eɪ": "A", "oʊ": "O", "ɔɪ": "Y", "dʒ": "ʤ", "tʃ": "ʧ", "ɚ": "əɹ"}


class UnknownWords:
    """misaki's fallback contract: token → (phonemes, rating), or (None, None) to skip the word."""

    def __init__(self, g2p: Any):
        self.g2p = g2p

    def __call__(self, token: Any) -> tuple[str | None, int | None]:
        try:
            found = self.g2p.pronounce([token.text]).get(token.text)
        except Exception:  # e.g. offline before the model was downloaded: Kokoro skips the word
            return None, None
        if found is None or not found.variants:
            return None, None
        return "".join(TO_MISAKI.get(p, p) for p in found.variants[0]), 1


def wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes((np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes())
    return buf.getvalue()

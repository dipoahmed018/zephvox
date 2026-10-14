"""espeak-ng rules via `phonemizer`: covers any word (names, numbers, new words) and UK English."""

from __future__ import annotations

import importlib.util
from typing import Any

from ...engine.models import Pronunciation
from ...engine.phonemes import normalize
from ..base import Availability, G2PProvider, ProviderSettings


class EspeakG2P(G2PProvider):
    name = "espeak"

    class Settings(ProviderSettings):
        language: str = "en-us"  # or "en-gb"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._backend = None

    def check_available(self) -> Availability:
        if importlib.util.find_spec("phonemizer") is None:
            return Availability(False, "python package 'phonemizer' not installed (uv sync --extra models)")
        from phonemizer.backend import EspeakBackend

        if not EspeakBackend.is_available():
            return Availability(False, "espeak-ng not installed (sudo pacman -S espeak-ng)")
        return Availability(True)

    def capabilities(self) -> dict[str, Any]:
        return {"accents": ["en-us", "en-gb"], "variants": False, "phoneme_set": "canonical-ipa"}

    def pronounce(self, words: list[str]) -> dict[str, Pronunciation]:
        if not words:
            return {}
        from phonemizer.separator import Separator

        if self._backend is None:
            from phonemizer.backend import EspeakBackend

            self._backend = EspeakBackend(self.settings.language, with_stress=False)
        lines = self._backend.phonemize(words, separator=Separator(phone=" ", word="|", syllable=""), strip=True)
        result = {}
        for word, line in zip(words, lines, strict=True):
            phones = normalize(line.replace("|", " ").split())
            result[word] = Pronunciation(word, [phones] if phones else [], self.name if phones else "")
        return result

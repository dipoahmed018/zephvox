"""speakcheck plugin: espeak-ng rules via `phonemizer` for any word (names, numbers, new words), US or UK.

GPL-3.0-or-later, like phonemizer and espeak-ng, and kept out of speakcheck itself for that reason.
Installing it registers the `espeak` G2P driver; use it with e.g. `order = ["cmudict", "espeak"]`.

Uses the espeak-ng library bundled in the `espeakng-loader` wheel (Linux, Windows, macOS), so no
system install is needed and every machine gets the same version. `PHONEMIZER_ESPEAK_LIBRARY`
picks another copy; without either, phonemizer looks for a system espeak-ng.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any

from speakcheck.engine.capabilities import install_hint
from speakcheck.engine.models import Pronunciation
from speakcheck.engine.phonemes import normalize
from speakcheck.providers.base import Availability, G2PProvider, ProviderSettings


def use_bundled_espeak() -> bool:
    """Point phonemizer at the bundled espeak-ng unless the user chose a library. True if bundled."""
    if os.environ.get("PHONEMIZER_ESPEAK_LIBRARY") or importlib.util.find_spec("espeakng_loader") is None:
        return False
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
    return True


class EspeakG2P(G2PProvider):
    name = "espeak"

    class Settings(ProviderSettings):
        language: str = "en-us"  # or "en-gb"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._backend = None
        self._bundled = False

    def check_available(self) -> Availability:
        if importlib.util.find_spec("phonemizer") is None:
            return Availability(False, "python package 'phonemizer' not installed (uv sync --extra espeak)")
        self._bundled = use_bundled_espeak()
        from phonemizer.backend import EspeakBackend

        if not EspeakBackend.is_available():
            return Availability(False, f"espeak-ng not installed ({install_hint('espeak-ng')})")
        return Availability(True)

    def capabilities(self) -> dict[str, Any]:
        return {"accents": ["en-us", "en-gb"], "variants": False, "phoneme_set": "canonical-ipa", "any_word": True,
                "library": "bundled" if self._bundled else "system"}  # fmt: skip

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

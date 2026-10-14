"""US or UK dictionaries from misaki, Kokoro's text front end (Apache-2.0).

~90k checked ("gold") and ~100k more ("silver") words per accent. The UK ones make this the driver
for British English: `order = ["misaki", "deep-phonemizer"]` and `accent = "en-gb"`.
"""

from __future__ import annotations

import importlib.util
import json
import re
from importlib.resources import files
from typing import Any

from ...engine.models import Pronunciation
from ...engine.phonemes import split_ipa
from ..base import Availability, G2PProvider, ProviderSettings

# misaki writes some phones as one letter.
SHORTHAND = {"A": "eɪ", "I": "aɪ", "O": "oʊ", "Q": "əʊ", "W": "aʊ", "Y": "ɔɪ", "ʤ": "dʒ", "ʧ": "tʃ", "ᵊ": "ə"}
VOWELS = "AIOQWYaeiouæɑɒɔəɛɜɪʊʌᵊᵻ"
R_COLORED = re.compile(f"[ɜə]ɹ(?![ˈˌː]*[{VOWELS}])")  # "butter" bʌɾəɹ → ɚ, but "arise" əɹIz keeps ɹ


def misaki_to_phones(text: str) -> list[str]:
    text = R_COLORED.sub("ɚ", text)
    return split_ipa("".join(SHORTHAND.get(c, c) for c in text))


class MisakiG2P(G2PProvider):
    name = "misaki"

    class Settings(ProviderSettings):
        accent: str = "en-us"  # or "en-gb"
        silver: bool = True  # also the larger, less checked dictionary

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._dicts: list[dict[str, Any]] | None = None

    def check_available(self) -> Availability:
        if self.settings.accent not in ("en-us", "en-gb"):
            return Availability(False, f"accent must be en-us or en-gb, not {self.settings.accent!r}")
        if importlib.util.find_spec("misaki") is None:
            return Availability(False, "python package 'misaki' not installed (uv sync --extra models)")
        return Availability(True)

    def capabilities(self) -> dict[str, Any]:
        return {"accents": [self.settings.accent], "variants": True, "phoneme_set": "canonical-ipa"}

    def _load(self) -> list[dict[str, Any]]:
        if self._dicts is None:
            prefix = "gb" if self.settings.accent == "en-gb" else "us"
            names = ["gold", "silver"] if self.settings.silver else ["gold"]
            data = files("misaki.data")
            self._dicts = [json.loads(data.joinpath(f"{prefix}_{n}.json").read_text(encoding="utf-8")) for n in names]
        return self._dicts

    def _entry(self, word: str) -> Any:
        for table in self._load():
            for form in dict.fromkeys((word, word.lower(), word.capitalize())):
                if table.get(form):
                    return table[form]
        return None

    def pronounce(self, words: list[str]) -> dict[str, Pronunciation]:
        result = {}
        for word in words:
            entry = self._entry(word)
            # Words spelled alike but said differently ("read") list one form per part of speech.
            forms = [entry.get("DEFAULT"), *entry.values()] if isinstance(entry, dict) else [entry]
            variants: list[list[str]] = []
            for form in forms:
                phones = misaki_to_phones(form) if form else []
                if phones and phones not in variants:
                    variants.append(phones)
            result[word] = Pronunciation(word, variants, self.name if variants else "")
        return result

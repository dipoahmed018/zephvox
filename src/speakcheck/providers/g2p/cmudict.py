"""CMU Pronouncing Dictionary: ~134k US-English words with all accepted variants."""

from __future__ import annotations

import importlib.util
from typing import Any

from ...engine.models import Pronunciation
from ...engine.phonemes import arpabet_to_ipa
from ..base import Availability, G2PProvider


class CMUDictG2P(G2PProvider):
    name = "cmudict"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._dict: dict[str, list[list[str]]] | None = None

    def check_available(self) -> Availability:
        if importlib.util.find_spec("cmudict") is None:
            return Availability(False, "python package 'cmudict' not installed")
        return Availability(True)

    def capabilities(self) -> dict[str, Any]:
        return {"accents": ["en-us"], "variants": True, "phoneme_set": "canonical-ipa"}

    def _lookup(self) -> dict[str, list[list[str]]]:
        if self._dict is None:
            import cmudict

            self._dict = cmudict.dict()
        return self._dict

    def pronounce(self, words: list[str]) -> dict[str, Pronunciation]:
        table = self._lookup()
        result = {}
        for word in words:
            variants: list[list[str]] = []
            for entry in table.get(word.lower(), []):
                ipa = arpabet_to_ipa(entry)
                if ipa not in variants:
                    variants.append(ipa)
            result[word] = Pronunciation(word, variants, self.name if variants else "")
        return result

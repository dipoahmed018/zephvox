"""CMU Pronouncing Dictionary: ~134k US-English words with all accepted variants.

The dictionary ships with zephvox (`data/cmudict`, BSD-style license from Carnegie Mellon).
"""

from __future__ import annotations

import re
from importlib.resources import files
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
        return Availability(True)

    def capabilities(self) -> dict[str, Any]:
        return {"accents": ["en-us"], "variants": True, "phoneme_set": "canonical-ipa"}

    def _lookup(self) -> dict[str, list[list[str]]]:
        if self._dict is None:
            self._dict = load_cmudict()
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


_VARIANT = re.compile(r"\(\d+\)$")


def load_cmudict() -> dict[str, list[list[str]]]:
    """word → ARPAbet variants. Lines look like `read(2) R EH1 D  # comment`."""
    table: dict[str, list[list[str]]] = {}
    text = files("zephvox.data").joinpath("cmudict", "cmudict.dict").read_text(encoding="utf-8")
    for line in text.splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) > 1:
            table.setdefault(_VARIANT.sub("", parts[0]), []).append(parts[1:])
    return table

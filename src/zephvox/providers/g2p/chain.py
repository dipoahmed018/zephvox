"""Try several G2P providers in order, per word (default: dictionary first, a guess as fallback).

Before guessing, short acronyms are spelled out ("GPT" → G P T) and words made of parts are split
("ChatGPT" → Chat + GPT, "e-mail" → e + mail), so the dictionary can still answer for each part.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ...engine.models import Pronunciation
from ..base import Availability, G2PProvider, ProviderSettings


class ChainG2P(G2PProvider):
    name = "chain"

    class Settings(ProviderSettings):
        order: list[str] = ["cmudict", "deep-phonemizer"]

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._members: list[G2PProvider] | None = None
        self.skipped: dict[str, str] = {}

    def _available_members(self) -> list[G2PProvider]:
        if self._members is None:
            if self.services.build is None:
                raise RuntimeError("ChainG2P needs Services.build to construct its members")
            self._members = []
            for name in self.settings.order:
                if name == self.name:
                    continue
                try:
                    member = self.services.build("g2p", name)
                except Exception as e:
                    self.skipped[name] = str(e)
                    continue
                ok, reason = member.check_available()
                if ok:
                    self._members.append(member)
                else:
                    self.skipped[name] = reason
        return self._members

    def check_available(self) -> Availability:
        if not self._available_members():
            detail = "; ".join(f"{n}: {r}" for n, r in self.skipped.items())
            return Availability(False, f"no member available ({detail})")
        return Availability(True)

    def capabilities(self) -> dict[str, Any]:
        return {"members": [m.name for m in self._available_members()], "skipped": dict(self.skipped)}

    def pronounce(self, words: list[str]) -> dict[str, Pronunciation]:
        spelled = {w: list(w.lower()) for w in words if ACRONYM.match(w)}
        letters = self._lookup(sorted({c for cs in spelled.values() for c in cs}), lambda m: True)
        result = {w: join(w, [letters[c] for c in cs]) for w, cs in spelled.items()}
        result |= self._lookup([w for w in words if w not in spelled], lambda m: not guesses(m))
        parts = {w: PART.findall(w) for w, p in result.items() if not p.variants}
        parts = {w: ps for w, ps in parts.items() if len(ps) > 1}
        if parts:
            found = self.pronounce(sorted({p for ps in parts.values() for p in ps}))
            for word, ps in parts.items():
                result[word] = join(word, [found[p] for p in ps])
        unknown = [w for w in words if not result[w].variants]
        result |= self._lookup(unknown, guesses)
        return result

    def _lookup(self, words: list[str], use: Callable[[G2PProvider], bool]) -> dict[str, Pronunciation]:
        result: dict[str, Pronunciation] = {}
        remaining = list(words)
        for member in self._available_members():
            if not remaining:
                break
            if not use(member):
                continue
            try:
                found = member.pronounce(remaining)
            except Exception as e:  # e.g. its model can't be downloaded: leave the words unjudged
                self.skipped[member.name] = str(e)
                continue
            for word in remaining:
                p = found.get(word)
                if p is not None and p.variants:
                    result[word] = p
            remaining = [w for w in remaining if w not in result]
        for word in remaining:
            result[word] = Pronunciation(word, [], "")
        return result


ACRONYM = re.compile(r"^[A-Z]{2,3}$")  # "TV", "GPT"; longer ones ("NASA", "COVID") are usually said as words
PART = re.compile(r"[A-Z]{2,}(?![a-z])|[A-Z]?[a-z']+|[A-Z]")


def guesses(member: G2PProvider) -> bool:
    """Drivers that predict any word: asked last, after the dictionaries had a go at each part."""
    return bool(member.capabilities().get("any_word"))


def join(word: str, parts: list[Pronunciation]) -> Pronunciation:
    if not parts or not all(p.variants for p in parts):
        return Pronunciation(word, [], "")
    return Pronunciation(word, [[ph for p in parts for ph in p.variants[0]]], "+".join(dict.fromkeys(p.source for p in parts)))

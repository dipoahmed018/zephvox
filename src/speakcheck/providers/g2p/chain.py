"""Try several G2P providers in order, per word (default: dictionary first, rules as fallback)."""

from __future__ import annotations

from typing import Any

from ...engine.models import Pronunciation
from ..base import Availability, G2PProvider, ProviderSettings


class ChainG2P(G2PProvider):
    name = "chain"

    class Settings(ProviderSettings):
        order: list[str] = ["cmudict", "espeak"]

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
        result: dict[str, Pronunciation] = {}
        remaining = list(words)
        for member in self._available_members():
            if not remaining:
                break
            found = member.pronounce(remaining)
            for word in remaining:
                p = found.get(word)
                if p is not None and p.variants:
                    result[word] = p
            remaining = [w for w in remaining if w not in result]
        for word in remaining:
            result[word] = Pronunciation(word, [], "")
        return result

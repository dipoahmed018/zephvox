"""Analyzer (ability) contract. Implement this to teach the engine to catch a new kind of mistake."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from ..engine.models import Finding


class AnalyzerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisContext:
    """What an analyzer may touch while running: artifacts, providers, warnings, progress."""

    def __init__(
        self,
        get: Callable[[str], Any],
        provider: Callable[[str], Any],
        warn: Callable[[str], None],
        progress: Callable[[str, float], None] | None = None,
    ):
        self.get = get
        self.provider = provider
        self.warn = warn
        self._progress = progress

    def progress(self, message: str, fraction: float) -> None:
        if self._progress:
            self._progress(message, fraction)


class Analyzer:
    name: ClassVar[str]
    # Artifacts this analyzer reads (see engine.artifacts) and provider kinds it calls directly.
    needs: ClassVar[tuple[str, ...]] = ()
    uses: ClassVar[tuple[str, ...]] = ()
    Settings: ClassVar[type[AnalyzerSettings]] = AnalyzerSettings

    def __init__(self, settings: dict[str, Any] | None = None):
        self.settings = self.Settings(**(settings or {}))

    def analyze(self, ctx: AnalysisContext) -> list[Finding]:
        raise NotImplementedError

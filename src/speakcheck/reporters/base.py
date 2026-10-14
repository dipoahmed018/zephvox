"""Reporter contract: render an AnalysisResult. Reporters only ever see Findings."""

from __future__ import annotations

from typing import ClassVar

from ..engine.models import AnalysisResult, Finding


class Reporter:
    name: ClassVar[str]
    extension: ClassVar[str] = "txt"

    def render(self, result: AnalysisResult) -> str:
        raise NotImplementedError


def fmt_time(seconds: float) -> str:
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes)}:{secs:04.1f}"


def group(result: AnalysisResult) -> list[tuple[str, list[Finding]]]:
    """Findings grouped by analyzer, in the order the analyzers ran."""
    order = list(result.analyzers) + sorted({f.analyzer for f in result.findings} - set(result.analyzers))
    groups = []
    for name in order:
        found = sorted(result.by_analyzer(name), key=lambda f: (f.segment_index, (f.word_span or (0, 0))[0]))
        groups.append((name, found))
    return groups


def headline(f: Finding) -> str:
    if f.analyzer == "pronunciation":
        return f"{f.target}: you said {f.said}, expected {f.expected}"
    return f'"{f.said}" → "{f.expected}"'

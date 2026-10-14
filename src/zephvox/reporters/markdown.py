from __future__ import annotations

from ..engine.models import AnalysisResult
from .base import Reporter, fmt_time, group


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


class MarkdownReporter(Reporter):
    name = "markdown"
    extension = "md"

    def render(self, result: AnalysisResult) -> str:
        lines = [
            f"# Speaking report — {result.session_id}",
            "",
            f"{len(result.sentences)} sentence(s), {fmt_time(result.duration)} of audio. "
            + "Providers: " + ", ".join(f"`{k}={v}`" for k, v in result.providers.items()),
            "",
        ]  # fmt: skip
        for name, findings in group(result):
            lines += [f"## {name.capitalize()} ({len(findings)})", ""]
            if not findings:
                lines += ["No mistakes found.", ""]
                continue
            lines += ["| # | Word / phrase | You said | Correct | Why | Sentence |", "|---|---|---|---|---|---|"]
            for i, f in enumerate(findings, 1):
                cells = [str(i), f.target, f.said, f.expected, f.explanation, f"“{f.sentence}”"]
                lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
            lines.append("")
        if result.warnings:
            lines += ["## Warnings", ""] + [f"- {_cell(w)}" for w in result.warnings] + [""]
        return "\n".join(lines)

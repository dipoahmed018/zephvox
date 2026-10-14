from __future__ import annotations

from ..engine.models import AnalysisResult
from .base import Reporter, fmt_time, group, headline


class TerminalReporter(Reporter):
    name = "terminal"

    def render(self, result: AnalysisResult) -> str:
        lines = [
            f"Session {result.session_id} · {len(result.sentences)} sentence(s) · {fmt_time(result.duration)}",
            "Providers: " + " · ".join(f"{k}={v}" for k, v in result.providers.items()),
            "",
        ]
        for name, findings in group(result):
            lines.append(f"{name.capitalize()} ({len(findings)})")
            if not findings:
                lines.append("  No mistakes found.")
            for i, f in enumerate(findings, 1):
                when = f" [{fmt_time(f.time_span[0])}]" if f.time_span else ""
                lines.append(f"  {i}. {headline(f)}  ({f.category})")
                if f.explanation:
                    lines.append(f"     {f.explanation}")
                lines.append(f"     “{f.sentence}”{when}")
            lines.append("")
        if result.warnings:
            lines.append("Warnings:")
            lines.extend(f"  - {w}" for w in result.warnings)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

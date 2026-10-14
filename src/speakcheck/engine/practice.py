"""Practice attempts: speak a known word/sentence again and keep score over time."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class PracticeAttempt:
    target: str
    score: int  # 0–100
    passed: bool
    words: list[dict[str, Any]] = field(default_factory=list)  # per-word details from the scorer
    at: str = ""
    audio: str | None = None
    source_session: str | None = None
    status: str = "ok"  # ok | no_speech | different_word

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PracticeStore:
    """Append-only log in `<data_dir>/practice.jsonl`; attempt audio in `<data_dir>/practice/`."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.log_path = self.root / "practice.jsonl"
        self.audio_dir = self.root / "practice"

    def new_audio_path(self, now: datetime | None = None) -> Path:
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S-%f")
        return self.audio_dir / f"{stamp}.wav"

    def add(self, attempt: PracticeAttempt) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as f:
            f.write(json.dumps(attempt.to_dict(), ensure_ascii=False) + "\n")

    def attempts(self, target: str | None = None) -> list[PracticeAttempt]:
        if not self.log_path.exists():
            return []
        out = []
        for line in self.log_path.read_text().splitlines():
            if not line.strip():
                continue
            attempt = PracticeAttempt(**json.loads(line))
            if target is None or attempt.target.lower() == target.lower():
                out.append(attempt)
        return out

    def stats(self, target: str) -> dict[str, Any]:
        attempts = self.attempts(target)
        return {
            "target": target,
            "attempts": len(attempts),
            "best": max((a.score for a in attempts), default=None),
            "last": attempts[-1].score if attempts else None,
            "passed": bool(attempts) and attempts[-1].passed,
            "history": [{"score": a.score, "passed": a.passed, "at": a.at} for a in attempts],
        }

    def weak_words(self, mistakes: list[tuple[str, int]], limit: int = 20) -> list[dict[str, Any]]:
        """Most frequent mistaken targets that haven't been passed in their latest practice."""
        out = []
        for target, count in mistakes:
            stats = self.stats(target)
            if stats["passed"]:
                continue
            out.append({"target": target, "mistakes": count, "best": stats["best"], "attempts": stats["attempts"]})
            if len(out) >= limit:
                break
        return out

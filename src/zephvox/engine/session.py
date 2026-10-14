"""On-disk sessions: one directory per recording/analysis."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import ZephvoxError
from .models import AnalysisResult


@dataclass(frozen=True)
class Session:
    id: str
    dir: Path

    @property
    def audio_path(self) -> Path:
        return self.dir / "audio.wav"

    @property
    def result_path(self) -> Path:
        return self.dir / "result.json"

    @property
    def feedback_path(self) -> Path:
        return self.dir / "feedback.json"


class SessionStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def create(self, now: datetime | None = None) -> Session:
        self.root.mkdir(parents=True, exist_ok=True)
        base = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        sid, n = base, 1
        while (self.root / sid).exists():
            n += 1
            sid = f"{base}-{n}"
        (self.root / sid).mkdir()
        return Session(sid, self.root / sid)

    def get(self, sid: str) -> Session:
        path = self.root / sid
        if not path.is_dir():
            raise ZephvoxError(f"No session {sid!r} in {self.root}")
        return Session(sid, path)

    def list(self) -> list[Session]:
        if not self.root.exists():
            return []
        return [Session(p.name, p) for p in sorted(self.root.iterdir()) if p.is_dir()]

    def save_result(self, session: Session, result: AnalysisResult) -> None:
        session.result_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

    def load_result(self, session: Session) -> AnalysisResult | None:
        if not session.result_path.exists():
            return None
        data: dict[str, Any] = json.loads(session.result_path.read_text())
        return AnalysisResult.from_dict(data)

    def delete(self, session: Session) -> None:
        shutil.rmtree(session.dir, ignore_errors=True)

    def load_feedback(self, session: Session) -> dict[int, str]:
        """User verdicts on findings, by index in `result.findings` (e.g. {3: "dismissed"})."""
        if not session.feedback_path.exists():
            return {}
        return {int(k): v for k, v in json.loads(session.feedback_path.read_text()).items()}

    def set_feedback(self, session: Session, index: int, verdict: str | None) -> dict[int, str]:
        feedback = self.load_feedback(session)
        if verdict is None:
            feedback.pop(index, None)
        else:
            feedback[index] = verdict
        session.feedback_path.write_text(json.dumps({str(k): v for k, v in sorted(feedback.items())}))
        return feedback

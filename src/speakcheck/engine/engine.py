"""The engine: orchestrates plugins. Knows nothing about pronunciation or grammar itself."""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..analyzers.base import AnalysisContext, Analyzer
from ..providers.base import CaptureProvider, Provider, Services
from . import audio
from .artifacts import ArtifactRegistry, ArtifactStore
from .capabilities import SystemCapabilities, detect
from .config import PROVIDER_KINDS, Config, load_config
from .errors import PluginNotFound, ProviderUnavailable, RecordingError, SpeakcheckError
from .events import EventBus
from .models import AnalysisResult, AudioRef
from .planner import plan
from .practice import PracticeAttempt, PracticeStore
from .registry import Registry
from .session import Session, SessionStore
from .text import transcript_from_text


@dataclass
class ProviderStatus:
    kind: str
    name: str
    available: bool
    reason: str
    selected: bool = False
    preference: int | None = None  # position in the configured preference list


@dataclass
class Recording:
    mode: str  # "analysis" | "practice"
    path: str
    session_id: str | None
    provider: str
    started: float
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Engine:
    def __init__(
        self,
        config: Config | None = None,
        registry: Registry | None = None,
        caps: SystemCapabilities | None = None,
        events: EventBus | None = None,
        artifacts: ArtifactRegistry | None = None,
    ):
        self.config = config or load_config()
        self.registry = registry or Registry()
        self.events = events or EventBus()
        self.artifacts = artifacts or ArtifactRegistry.default()
        self.sessions = SessionStore(self.config.engine.data_dir / "sessions")
        self._caps = caps
        self._providers: dict[str, Provider] = {}
        # Recording (capture) may run while an analysis uses other providers on another thread.
        self._provider_lock = threading.RLock()

    # --- system & providers -------------------------------------------------------------

    @property
    def caps(self) -> SystemCapabilities:
        if self._caps is None:
            self._caps = detect()
        return self._caps

    def _services(self) -> Services:
        return Services(caps=self.caps, build=self.build_provider)

    def build_provider(self, kind: str, name: str) -> Provider:
        cls = self.registry.get(kind, name)
        return cls(self.config.provider_settings(name), self._services())

    def provider(self, kind: str) -> Provider:
        """The first available provider from the configured preference list (cached)."""
        with self._provider_lock:
            return self._resolve_provider(kind)

    def _resolve_provider(self, kind: str) -> Provider:
        if kind in self._providers:
            return self._providers[kind]
        reasons = []
        for name in self.config.providers.get(kind, []):
            try:
                candidate = self.build_provider(kind, name)
            except PluginNotFound as e:
                reasons.append(str(e))
                continue
            status = candidate.check_available()
            if status.ok:
                try:
                    candidate.prepare()
                except SpeakcheckError as e:
                    candidate.close()
                    reasons.append(f"{name}: {e}")
                    continue
                if reasons:
                    self.events.emit("provider_fallback", kind=kind, name=name, skipped=reasons)
                self.events.emit("provider_selected", kind=kind, name=name)
                self._providers[kind] = candidate
                return candidate
            reasons.append(f"{name}: {status.reason}")
        raise ProviderUnavailable(kind, reasons)

    def list_providers(self) -> list[ProviderStatus]:
        statuses = []
        for kind in PROVIDER_KINDS:
            preferred = self.config.providers.get(kind, [])
            selected_found = False
            for name in self.registry.names(kind):
                candidate = self.build_provider(kind, name)
                ok, reason = candidate.check_available()
                pref = preferred.index(name) if name in preferred else None
                statuses.append(ProviderStatus(kind, name, ok, reason, preference=pref))
            # Mark the one `provider()` would pick.
            for name in preferred:
                for s in statuses:
                    if s.kind == kind and s.name == name and s.available and not selected_found:
                        s.selected = selected_found = True
        return statuses

    def doctor(self) -> dict[str, Any]:
        return {
            "system": self.caps.to_dict(),
            "providers": [vars(s) for s in self.list_providers()],
            "analyzers": self.registry.names("analyzers"),
            "reporters": self.registry.names("reporters"),
            "broken_plugins": {f"{k}:{n}": err for (k, n), err in self.registry.broken.items()},
        }

    def close(self) -> None:
        with self._provider_lock:
            for p in self._providers.values():
                p.close()
            self._providers.clear()

    def release(self, kind: str) -> None:
        """Close and forget one provider (e.g. stop an autostarted LLM server between jobs)."""
        with self._provider_lock:
            provider = self._providers.pop(kind, None)
        if provider is not None:
            provider.close()

    # --- recording ----------------------------------------------------------------------

    @property
    def _recording_state(self) -> Path:
        return self.config.engine.data_dir / "recording.json"

    def is_recording(self) -> bool:
        return self._recording_state.exists()

    def start_recording(self, mode: str = "analysis", meta: dict[str, Any] | None = None) -> Recording:
        """Record from the microphone. `mode="practice"` records a short attempt outside any session."""
        if mode not in ("analysis", "practice"):
            raise RecordingError(f"Unknown recording mode {mode!r}")
        if self.is_recording():
            raise RecordingError("Already recording; stop the current recording first")
        capture = self.provider("capture")
        assert isinstance(capture, CaptureProvider)
        session = self.sessions.create() if mode == "analysis" else None
        path = session.audio_path if session else self.practice_store.new_audio_path()
        handle = capture.start(path)
        recording = Recording(
            mode=mode,
            path=str(path),
            session_id=session.id if session else None,
            provider=capture.name,
            started=time.time(),
            meta=dict(meta or {}),
        )
        self.config.engine.data_dir.mkdir(parents=True, exist_ok=True)
        self._recording_state.write_text(json.dumps({**recording.to_dict(), "handle": handle}))
        self.events.emit("recording_started", **recording.to_dict())
        return recording

    def _load_recording(self) -> tuple[Recording, dict[str, Any], CaptureProvider]:
        if not self.is_recording():
            raise RecordingError("Not recording")
        state = json.loads(self._recording_state.read_text())
        handle = state.pop("handle")
        recording = Recording(**state)
        # Use the provider that started it (it holds in-process streams), even if preferences changed.
        capture = self._providers.get("capture")
        if capture is None or capture.name != recording.provider:
            capture = self.build_provider("capture", recording.provider)
        return recording, handle, capture  # type: ignore[return-value]

    def stop_recording(self) -> Recording:
        recording, handle, capture = self._load_recording()
        try:
            capture.stop(handle)
        finally:
            self._recording_state.unlink(missing_ok=True)
        self.events.emit("recording_stopped", **recording.to_dict())
        return recording

    def cancel_recording(self) -> Recording:
        """Stop and throw the recording away."""
        recording, handle, capture = self._load_recording()
        try:
            capture.stop(handle)
        except RecordingError:
            pass  # nothing recorded is fine when discarding
        finally:
            self._recording_state.unlink(missing_ok=True)
        if recording.session_id:
            self.sessions.delete(self.sessions.get(recording.session_id))
        else:
            Path(recording.path).unlink(missing_ok=True)
        self.events.emit("recording_cancelled", **recording.to_dict())
        return recording

    def recording_status(self) -> dict[str, Any] | None:
        if not self.is_recording():
            return None
        recording, handle, capture = self._load_recording()
        return {
            **recording.to_dict(),
            "elapsed": round(time.time() - recording.started, 1),
            "level": capture.level(handle),
            "device": capture.settings.model_dump().get("device"),
        }

    # --- analysis -----------------------------------------------------------------------

    def _analyzers(self, names: list[str]) -> list[Analyzer]:
        return [self.registry.get("analyzers", n)(self.config.analyzer_settings(n)) for n in names]

    def analyze(
        self,
        source: Session | Recording | Path | str,
        analyzers: list[str] | None = None,
        reference_text: str | None = None,
        save: bool = True,
    ) -> AnalysisResult:
        """Analyze a session, a finished recording, or any audio file.

        `reference_text`: the words are already known (practice), so no speech-to-text runs.
        `save=False`: don't create or update a session (result has an empty `session_id`).
        """
        if isinstance(source, Recording):
            source = self.sessions.get(source.session_id) if source.session_id else Path(source.path)
        session: Session | None = source if isinstance(source, Session) else None
        samples = audio.decode(session.audio_path if session else source)
        if session is None and save:
            session = self.sessions.create()
            audio.write_wav(session.audio_path, samples)
        audio_path = session.audio_path if session else Path(source)

        initial: dict[str, Any] = {"audio": AudioRef(audio_path), "samples": samples}
        if reference_text is not None:
            initial["transcript"] = transcript_from_text(reference_text, audio.duration(samples))

        names = analyzers or self.config.engine.analyzers
        instances = self._analyzers(names)
        the_plan = plan([(a.needs, a.uses) for a in instances], self.artifacts, provided=tuple(initial))
        # Resolve every provider up front so we fail before any heavy work.
        for kind in the_plan.provider_kinds:
            self.provider(kind)

        store = ArtifactStore(
            self.artifacts,
            self.provider,
            self.events,
            initial=initial,
            options={"sentence_split": self.config.engine.sentence_split},
        )
        for key in the_plan.artifacts:
            store.get(key)

        warnings: list[str] = []

        def warn(message: str) -> None:
            warnings.append(message)
            self.events.emit("warning", message=message)

        findings = []
        for analyzer in instances:
            self.events.emit("stage_started", stage=f"analyzer:{analyzer.name}")
            ctx = AnalysisContext(
                store.get,
                self.provider,
                warn,
                lambda msg, frac, _n=analyzer.name: self.events.emit("progress", stage=_n, message=msg, fraction=frac),
            )
            found = analyzer.analyze(ctx)
            for f in found:
                self.events.emit("finding", finding=f)
            findings.extend(found)
            self.events.emit("stage_finished", stage=f"analyzer:{analyzer.name}")

        transcript = store.peek("transcript")
        result = AnalysisResult(
            session_id=session.id if session else "",
            audio_path=str(audio_path),
            sentences=[s.text for s in transcript.segments] if transcript else [],
            sentence_spans=[(round(s.start, 2), round(s.end, 2)) for s in transcript.segments] if transcript else [],
            findings=findings,
            providers={k: self._providers[k].name for k in the_plan.provider_kinds},
            analyzers=names,
            warnings=warnings,
            timings={k: round(v, 3) for k, v in store.timings.items()},
            duration=round(audio.duration(samples), 2),
            created=datetime.now().isoformat(timespec="seconds"),
        )
        if session is not None:
            self.sessions.save_result(session, result)
        return result

    # --- practice -----------------------------------------------------------------------

    @property
    def practice_store(self) -> PracticeStore:
        return PracticeStore(self.config.engine.data_dir)

    def practice(self, target: str, source: Recording | Path | str,
                 source_session: str | None = None) -> PracticeAttempt:  # fmt: skip
        """Score one attempt at saying `target` and log it."""
        path = Path(source.path) if isinstance(source, Recording) else Path(source)
        result = self.analyze(path, [self.config.engine.practice_analyzer], reference_text=target, save=False)
        words = [{"word": f.target, "explanation": f.explanation, **f.details} for f in result.findings]
        scores = [w.get("score", 0) for w in words]
        statuses = {w.get("status", "ok") for w in words}
        status = next((s for s in ("no_speech", "different_word") if s in statuses), "ok")
        attempt = PracticeAttempt(
            target=target,
            score=round(sum(scores) / len(scores)) if scores else 0,
            passed=bool(words) and all(w.get("passed") for w in words),
            words=words,
            at=datetime.now().isoformat(timespec="seconds"),
            audio=str(path),
            source_session=source_session,
            status=status,
        )
        self.practice_store.add(attempt)
        self.events.emit("practice_result", attempt=attempt.to_dict())
        return attempt

    def weak_words(self, limit: int = 20) -> list[dict[str, Any]]:
        mistakes = self.history(limit=1000)["targets"].get("pronunciation", [])
        return self.practice_store.weak_words(mistakes, limit)

    # --- history ------------------------------------------------------------------------

    def history(self, limit: int = 10) -> dict[str, Any]:
        """Most frequent mistakes across all saved sessions (dismissed findings excluded)."""
        per_analyzer: dict[str, Counter] = {}
        targets: dict[str, Counter] = {}
        dismissed = 0
        sessions = 0
        for session in self.sessions.list():
            result = self.sessions.load_result(session)
            if result is None:
                continue
            sessions += 1
            feedback = self.sessions.load_feedback(session)
            for i, f in enumerate(result.findings):
                if feedback.get(i) == "dismissed":
                    dismissed += 1
                    continue
                per_analyzer.setdefault(f.analyzer, Counter())[f.category] += 1
                targets.setdefault(f.analyzer, Counter())[f.target.lower()] += 1
        return {
            "sessions": sessions,
            "dismissed": dismissed,
            "categories": {a: c.most_common(limit) for a, c in per_analyzer.items()},
            "targets": {a: c.most_common(limit) for a, c in targets.items()},
        }

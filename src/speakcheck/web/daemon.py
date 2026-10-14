"""The long-running daemon behind `speakcheck serve`.

Owns one Engine (so models stay loaded), runs engine jobs on a single worker thread, turns
shortcut presses and API calls into the same actions, and broadcasts every engine event to
connected pages.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..engine.config import ACTIONS, apply_user_settings, load_user_settings, save_user_settings
from ..engine.engine import Engine, Recording
from ..engine.errors import ProviderUnavailable, RecordingError, SpeakcheckError
from ..engine.events import Event

# Practice auto-stop: a level above SPEECH means the user started talking; staying below
# SILENCE for `practice_auto_stop_s` afterwards ends the attempt.
SPEECH_LEVEL = 0.45
SILENCE_LEVEL = 0.30
LEVEL_INTERVAL_S = 0.12


def jsonable(value: Any) -> Any:
    """Event payloads → JSON-safe data (dataclasses, paths, tuples)."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


class EventHub:
    """Fan engine events (from any thread) out to every connected page's asyncio queue."""

    def __init__(self) -> None:
        self._subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        with self._lock:
            self._subscribers.append((loop, queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers = [(lp, q) for lp, q in self._subscribers if q is not queue]

    def publish(self, type: str, data: dict[str, Any]) -> None:
        message = json.dumps({"type": type, "data": jsonable(data)}, ensure_ascii=False)
        with self._lock:
            subscribers = list(self._subscribers)
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(self._put, queue, message)
            except RuntimeError:  # that page's loop is gone
                self.unsubscribe(queue)

    @staticmethod
    def _put(queue: asyncio.Queue, message: str) -> None:
        if queue.full():
            queue.get_nowait()  # a stalled page loses the oldest events, never blocks the engine
        queue.put_nowait(message)


class Daemon:
    def __init__(self, engine: Engine, start_triggers: bool = True):
        self.engine = engine
        self.hub = EventHub()
        engine.events.subscribe(self._forward)
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="engine")
        self._jobs = 0
        self._jobs_lock = threading.Lock()
        self.practice_target: dict[str, Any] | None = None  # {"text": ..., "session_id": ...}
        self.analyzers_for_next: list[str] | None = None
        self.triggers: dict[str, Any] = {"driver": None, "active": False, "error": None, "description": ""}
        self._trigger_provider = None
        self._stop = threading.Event()
        self._ticker = threading.Thread(target=self._tick, name="level-ticker", daemon=True)
        self._ticker.start()
        if start_triggers:
            threading.Thread(target=self._start_triggers, name="triggers", daemon=True).start()

    # --- events -------------------------------------------------------------------------

    def _forward(self, event: Event) -> None:
        self.hub.publish(event.type, event.data)

    def publish(self, type: str, **data: Any) -> None:
        self.hub.publish(type, data)

    @property
    def busy(self) -> bool:
        return self._jobs > 0

    def _submit(self, name: str, fn: Callable[[], Any]) -> Future:
        with self._jobs_lock:
            self._jobs += 1
        self.publish("job_started", job=name)

        def run():
            try:
                return fn()
            except SpeakcheckError as e:
                self.publish("job_error", job=name, message=str(e))
                raise
            except Exception as e:  # never kill the worker silently
                self.publish("job_error", job=name, message=f"{type(e).__name__}: {e}")
                raise
            finally:
                with self._jobs_lock:
                    self._jobs -= 1
                self.publish("job_finished", job=name)

        return self._worker.submit(run)

    # --- actions (shared by shortcuts, API and CLI) ---------------------------------------

    def start(self, mode: str = "analysis", analyzers: list[str] | None = None) -> Recording:
        meta: dict[str, Any] = {}
        if mode == "practice":
            if not self.practice_target:
                raise RecordingError("Pick a word to practise first")
            meta = dict(self.practice_target)
        else:
            self.analyzers_for_next = analyzers
        return self.engine.start_recording(mode=mode, meta=meta)

    def stop(self) -> Recording:
        recording = self.engine.stop_recording()
        if recording.mode == "practice":
            meta = recording.meta
            self._submit("practice", lambda: self.engine.practice(meta["text"], recording, meta.get("session_id")))
        else:
            analyzers = self.analyzers_for_next
            self._submit("analysis", lambda: self._analyze(recording, analyzers))
        return recording

    def _analyze(self, recording: Recording, analyzers: list[str] | None):
        try:
            result = self.engine.analyze(recording, analyzers)
        finally:
            self.engine.release("llm")  # an autostarted Ollama only lives during the job
        self.publish("analysis_done", session_id=result.session_id)
        return result

    def cancel(self) -> Recording:
        return self.engine.cancel_recording()

    def toggle(self, mode: str = "analysis", analyzers: list[str] | None = None) -> Recording:
        status = self.engine.recording_status()
        if status is None:
            return self.start(mode, analyzers)
        if status["mode"] != mode:
            # A practice shortcut must never end (and analyze) a normal recording, or vice versa.
            raise RecordingError(f"A {status['mode']} recording is in progress; stop or cancel it first")
        return self.stop()

    def fire(self, action: str) -> None:
        """Run a shortcut action; errors become events instead of exceptions (no caller to catch them)."""
        try:
            if action == "toggle_recording":
                self.toggle("analysis")
            elif action == "practice_attempt":
                self.toggle("practice")
            elif action == "cancel":
                if self.engine.is_recording():
                    self.cancel()
            else:
                raise SpeakcheckError(f"Unknown action {action!r}")
        except SpeakcheckError as e:
            self.publish("action_error", action=action, message=str(e))

    def analyze_file(self, path: Path, analyzers: list[str] | None) -> Future:
        return self._submit("analysis", lambda: self._analyze_path(path, analyzers))

    def _analyze_path(self, path: Path, analyzers: list[str] | None):
        try:
            result = self.engine.analyze(path, analyzers)
        finally:
            self.engine.release("llm")
            path.unlink(missing_ok=True)
        self.publish("analysis_done", session_id=result.session_id)
        return result

    def set_practice_target(self, text: str | None, session_id: str | None = None) -> None:
        self.practice_target = {"text": text, "session_id": session_id} if text else None
        self.publish("practice_target", target=self.practice_target)

    # --- settings -------------------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        stored = load_user_settings(self.engine.config.engine.data_dir)
        return {
            "capture": stored.get("capture") or {},
            "analyzers": self.engine.config.engine.analyzers,
            "shortcuts": self.engine.config.shortcuts,
        }

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        data_dir = self.engine.config.engine.data_dir
        stored = load_user_settings(data_dir)
        stored.update({k: v for k, v in changes.items() if k in ("capture", "analyzers")})
        save_user_settings(data_dir, stored)
        self.engine.config = apply_user_settings(self.engine.config, stored)
        if "capture" in changes and not self.engine.is_recording():
            self.engine.release("capture")  # next recording uses the new device
        self.publish("settings_changed", settings=self.settings())
        return self.settings()

    # --- background: levels, auto-stop, shortcuts -------------------------------------------

    def _tick(self) -> None:
        heard_speech, quiet_since = False, None
        while not self._stop.wait(LEVEL_INTERVAL_S):
            try:
                status = self.engine.recording_status()
            except (SpeakcheckError, OSError, ValueError):
                status = None
            if status is None:
                heard_speech, quiet_since = False, None
                continue
            self.publish("level", level=status["level"], elapsed=status["elapsed"], mode=status["mode"])
            if status["mode"] != "practice":
                continue
            level = status["level"] or 0.0
            cfg = self.engine.config.engine
            if level >= SPEECH_LEVEL:
                heard_speech, quiet_since = True, None
            elif heard_speech and level < SILENCE_LEVEL:
                quiet_since = quiet_since or time.monotonic()
            too_long = status["elapsed"] >= cfg.practice_max_s
            silent_long = (cfg.practice_auto_stop_s > 0 and quiet_since is not None
                           and time.monotonic() - quiet_since >= cfg.practice_auto_stop_s)  # fmt: skip
            if too_long or silent_long:
                heard_speech, quiet_since = False, None
                try:
                    self.stop()
                except SpeakcheckError as e:
                    self.publish("action_error", action="auto_stop", message=str(e))

    def _start_triggers(self) -> None:
        bindings = {a: k for a, k in self.engine.config.shortcuts.items() if a in ACTIONS and k}
        try:
            provider = self.engine.provider("triggers")
            self.triggers.update(driver=provider.name, description=provider.describe())
            provider.start(bindings, self.fire)
            self._trigger_provider = provider
            self.triggers.update(active=True, error=None)
        except (ProviderUnavailable, SpeakcheckError) as e:
            self.triggers.update(active=False, error=str(e))
        self.publish("triggers", **self.triggers, bindings=bindings)

    # --- lifecycle --------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {
            "busy": self.busy,
            "recording": self.engine.recording_status(),
            "practice_target": self.practice_target,
            "triggers": {**self.triggers, "bindings": self.engine.config.shortcuts},
            "pid": os.getpid(),
        }

    def close(self) -> None:
        self._stop.set()
        if self.engine.is_recording():
            try:
                self.engine.cancel_recording()
            except SpeakcheckError:
                pass
        if self._trigger_provider is not None:
            try:
                self._trigger_provider.stop()
            except Exception:  # shutting down anyway
                pass
        self._worker.shutdown(wait=True, cancel_futures=True)
        self.engine.close()

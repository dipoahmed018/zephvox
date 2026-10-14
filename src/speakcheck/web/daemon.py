"""The long-running daemon behind `speakcheck serve`.

Owns one Engine (so models stay loaded), runs engine jobs on a single worker thread, turns
shortcut presses and API calls into the same actions, and broadcasts every engine event to
connected pages.
"""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import json
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..engine import hardware, profiles
from ..engine.config import (
    ACTIONS,
    apply_user_settings,
    choose_profile,
    default_config_path,
    load_config,
    load_user_settings,
    project_root,
    save_user_settings,
)
from ..engine.engine import Engine, Recording
from ..engine.errors import ProviderUnavailable, RecordingError, SpeakcheckError
from ..engine.events import Event
from ..engine.session import Session

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
        self._backend: Any = None  # LocalBackend | RemoteBackend, built on first use
        self._backend_lock = threading.Lock()
        self._sync: Any = None  # SyncWorker while a server is connected
        self.install = {"running": False, "ok": None, "log": []}
        self.analyzers_for_next: list[str] | None = None
        self.triggers: dict[str, Any] = {"driver": None, "active": False, "error": None, "description": ""}
        self._trigger_provider = None
        self._stop = threading.Event()
        self._ticker = threading.Thread(target=self._tick, name="level-ticker", daemon=True)
        self._ticker.start()
        if start_triggers:
            threading.Thread(target=self._start_triggers, name="triggers", daemon=True).start()
        self._restart_sync()

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

    # --- where analysis runs ----------------------------------------------------------------

    @property
    def backend(self) -> Any:
        """This computer's engine, or the server in client mode (see `client/backend.py`)."""
        from ..client.backend import make_backend

        with self._backend_lock:
            if self._backend is None:
                self._backend = make_backend(self.engine)
            return self._backend

    def _reset_backend(self) -> None:
        with self._backend_lock:
            old, self._backend = self._backend, None
        if old is not None:
            old.close()
        self._restart_sync()

    # --- background sync: history backup and the offline queue -------------------------------

    def _restart_sync(self) -> None:
        from ..client import credentials
        from ..client.backend import client_for
        from ..client.sync import SyncWorker

        old, self._sync = self._sync, None
        if old is not None:
            old.stop()
        remote = self.engine.config.remote
        if not remote.url or credentials.load(self.engine.config.engine.data_dir, remote.url) is None:
            return
        if remote.mode != "remote" and not remote.syncing:
            return
        self._sync = SyncWorker(self.engine, lambda: client_for(self.engine), history=remote.syncing,
                                analyze_pending=self._analyze_pending if remote.mode == "remote" else None,
                                publish=self.publish)  # fmt: skip
        self._sync.start()

    def sync_soon(self) -> None:
        if self._sync is not None:
            self._sync.trigger()

    def _analyze_pending(self, session: Session, analyzers: list[str] | None) -> None:
        """A recording queued while the server was unreachable (runs on the sync thread)."""
        result = self.backend.analyze(session, analyzers)
        self.publish("analysis_done", session_id=result.session_id, queued=True)

    # --- actions (shared by shortcuts, API and CLI) ---------------------------------------

    def start(self, mode: str = "analysis", analyzers: list[str] | None = None) -> Recording:
        meta: dict[str, Any] = {}
        if mode == "practice":
            if not self.practice_target:
                raise RecordingError("Pick a word to practice first")
            meta = dict(self.practice_target)
            backend = self.backend  # fail now (e.g. not connected) rather than after recording
        else:
            self.analyzers_for_next = analyzers
        recording = self.engine.start_recording(mode=mode, meta=meta)
        if mode == "practice" and backend.remote:
            # Open the stream while the user starts talking; audio follows from `_tick`.
            threading.Thread(target=backend.practice_begin, args=(meta["text"],), daemon=True).start()
        return recording

    def stop(self) -> Recording:
        recording = self.engine.stop_recording()
        if recording.mode == "practice":
            meta = recording.meta
            self._submit("practice", lambda: self.backend.practice(meta["text"], recording, meta.get("session_id")))
        else:
            analyzers = self.analyzers_for_next
            self._submit("analysis", lambda: self._analyze(recording, analyzers))
        return recording

    def _analyze(self, recording: Recording | Session, analyzers: list[str] | None):
        from ..client.remote import QueuedOffline

        try:
            result = self.backend.analyze(recording, analyzers)
        except QueuedOffline as e:
            self.publish("warning", message=str(e).split(" (")[0])
            self.publish("sessions_changed")
            self.sync_soon()
            return None
        self.publish("analysis_done", session_id=result.session_id)
        self.sync_soon()
        return result

    def cancel(self) -> Recording:
        recording = self.engine.cancel_recording()
        if recording.mode == "practice" and self._backend is not None:
            self._backend.practice_cancel()
        return recording

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

    def reanalyze(self, session_id: str, analyzers: list[str] | None) -> Future:
        """Analyze an existing session again, in place (e.g. after tuning thresholds)."""
        session = self.engine.sessions.get(session_id)
        return self._submit("analysis", lambda: self._analyze(session, analyzers))

    def analyze_file(self, path: Path, analyzers: list[str] | None) -> Future:
        return self._submit("analysis", lambda: self._analyze_path(path, analyzers))

    def _analyze_path(self, path: Path, analyzers: list[str] | None):
        try:
            return self._analyze(path, analyzers)
        finally:
            path.unlink(missing_ok=True)

    def set_practice_target(self, text: str | None, session_id: str | None = None) -> None:
        self.practice_target = {"text": text, "session_id": session_id} if text else None
        self.publish("practice_target", target=self.practice_target)

    # --- settings -------------------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        stored = load_user_settings(self.engine.config.engine.data_dir)
        return {
            "capture": stored.get("capture") or {},
            "tts": stored.get("tts") or {},
            "analyzers": self.engine.config.engine.analyzers,
            "shortcuts": self.engine.config.shortcuts,
        }

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        data_dir = self.engine.config.engine.data_dir
        stored = load_user_settings(data_dir)
        stored.update({k: v for k, v in changes.items() if k in ("capture", "tts", "analyzers")})
        save_user_settings(data_dir, stored)
        self.engine.config = apply_user_settings(self.engine.config, stored)
        if "capture" in changes and not self.engine.is_recording():
            self.engine.release("capture")  # next recording uses the new device
        if "tts" in changes:
            self.engine.release("tts")
        self.publish("settings_changed", settings=self.settings())
        return self.settings()

    # --- client mode: the server, this device's key, installing the engine here ------------------

    def engine_installed(self) -> bool:
        """Can analysis run on this computer (models extra + PyTorch installed)?"""
        import importlib.util

        return all(importlib.util.find_spec(m) is not None for m in ("torch", "transformers"))

    def remote_info(self, check: bool = True) -> dict[str, Any]:
        from ..client import credentials
        from ..client.backend import client_for
        from ..client.remote import ServerError, is_insecure

        remote = self.engine.config.remote
        data_dir = self.engine.config.engine.data_dir
        creds = credentials.load(data_dir, remote.url) if remote.url else None
        info: dict[str, Any] = {
            "mode": remote.mode,
            "url": remote.url,
            "headers": sorted(remote.headers),  # names only: values may be secrets
            "sync": remote.syncing,
            "connected": creds is not None,
            "device": creds.device_name if creds else None,
            "account": creds.account if creds else None,
            "insecure": bool(remote.url) and is_insecure(remote.url),
            "engine_installed": self.engine_installed(),
            "install": {k: (v[-200:] if k == "log" else v) for k, v in self.install.items()},
            "sync_status": dict(self._sync.status) if self._sync is not None else None,
            "reachable": None,
            "error": None,
        }
        if check and remote.url:
            client = client_for(self.engine)
            try:
                client.health()
                info["reachable"] = True
                if creds:
                    account = client.account()
                    info["account"] = account["name"]
            except ServerError as e:
                info["reachable"] = e.status is not None  # it answered, but said no
                info["error"] = str(e)
            finally:
                client.close()
        return info

    def _save_remote(self, changes: dict[str, Any]) -> None:
        data_dir = self.engine.config.engine.data_dir
        stored = load_user_settings(data_dir)
        remote = {**(stored.get("remote") or {}), **changes}
        stored["remote"] = remote
        save_user_settings(data_dir, stored)
        self.engine.config = apply_user_settings(self.engine.config, stored)
        self._reset_backend()

    def set_remote(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Mode, server address, headers or sync. Local mode needs the engine installed here."""
        if self.busy or self.engine.is_recording():
            raise SpeakcheckError("finish the current recording or analysis first")
        allowed = {k: v for k, v in changes.items() if k in ("mode", "url", "headers", "sync", "device_name")}
        if allowed.get("mode") == "local" and not self.engine_installed():
            raise SpeakcheckError("the engine isn't installed on this computer yet: install it first")
        if allowed.get("mode") == "remote" and not (allowed.get("url") or self.engine.config.remote.url):
            raise SpeakcheckError("enter the server's address first")
        if "url" in allowed:
            allowed["url"] = (allowed["url"] or "").strip().rstrip("/") or None
        self._save_remote(allowed)
        info = self.remote_info()
        self.publish("remote_changed", remote=info)
        return info

    def connect(self, url: str, invite: str, device_name: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        """Redeem an invite: this device gets its own key, and analysis moves to the server."""
        from ..client import credentials
        from ..client.remote import ServerClient

        url = url.strip().rstrip("/")
        headers = self.engine.config.remote.headers if headers is None else headers
        client = ServerClient(url, headers)
        try:
            client.health()
            data = client.redeem(invite, device_name)
        finally:
            client.close()
        data_dir = self.engine.config.engine.data_dir
        credentials.save(data_dir, credentials.Credentials(url, data["key"], data["device"]["id"],
                                                           data["device"]["name"], data.get("account") or ""))  # fmt: skip
        self._save_remote({"mode": "remote", "url": url, "headers": headers, "device_name": device_name})
        info = self.remote_info()
        self.publish("remote_changed", remote=info)
        return info

    def rotate_key(self) -> dict[str, Any]:
        """A new key for this device; the old one stops working on the server at once."""
        from ..client import credentials
        from ..client.backend import client_for

        data_dir = self.engine.config.engine.data_dir
        creds = credentials.load(data_dir, self.engine.config.remote.url)
        if creds is None:
            raise SpeakcheckError("this device isn't connected to a server")
        client = client_for(self.engine)
        try:
            creds.key = client.rotate()
        finally:
            client.close()
        credentials.save(data_dir, creds)
        self._reset_backend()
        return self.remote_info(check=False)

    def forget_key(self) -> dict[str, Any]:
        """Disconnect: revoke this device on the server (if reachable) and delete the local key."""
        from ..client import credentials
        from ..client.backend import client_for
        from ..client.remote import ServerError

        data_dir = self.engine.config.engine.data_dir
        creds = credentials.load(data_dir)
        if creds is not None and creds.device_id:
            client = client_for(self.engine, creds.url)
            try:
                client.revoke(creds.device_id)
            except ServerError:
                pass  # the key is deleted here either way
            finally:
                client.close()
        credentials.clear(data_dir)
        changes: dict[str, Any] = {"mode": "local"} if self.engine_installed() else {}
        self._save_remote(changes)
        info = self.remote_info(check=False)
        self.publish("remote_changed", remote=info)
        return info

    def start_install(self, then_local: bool = True, runner: Callable[..., Any] | None = None) -> dict[str, Any]:
        """Install the engine on this computer (`speakcheck setup --role full`) in the background."""
        import subprocess
        import sys

        from ..install.ollama import find as find_ollama

        if self.install["running"]:
            raise SpeakcheckError("the engine is already being installed")
        command = [sys.executable, "-m", "speakcheck.cli", "setup", "--role", "full", "--yes", "--no-launcher"]
        if self.engine.config.source:
            command += ["--config", str(self.engine.config.source)]
        if find_ollama() is None:
            command.append("--no-ollama")  # installing Ollama may need a password: do that in a terminal
        self.install.update(running=True, ok=None, log=[])
        self.publish("install", **self.install)
        popen = runner or subprocess.Popen

        def run() -> None:
            ok = False
            try:
                proc = popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                for line in proc.stdout:
                    line = line.rstrip()
                    self.install["log"].append(line)
                    self.publish("install_output", line=line)
                ok = proc.wait() == 0
            except OSError as e:
                self.install["log"].append(f"error: {e}")
            import importlib

            importlib.invalidate_caches()  # the new packages must be found without a restart
            if ok and then_local and self.engine_installed():
                path = self._config_path()
                if path.exists():  # setup wrote the chosen profile there
                    self.engine.config = load_config(path)
                self._save_remote({"mode": "local"})
            self.install.update(running=False, ok=ok)
            self.publish("install", **{**self.install, "log": self.install["log"][-20:]})
            self.publish("remote_changed", remote=self.remote_info(check=False))

        threading.Thread(target=run, name="install", daemon=True).start()
        return self.install

    # --- profiles -------------------------------------------------------------------------

    MODEL_KINDS = ("stt", "phonemes", "g2p", "tts", "llm")

    @functools.cached_property
    def hardware(self) -> hardware.Hardware:
        return hardware.detect()

    def _config_path(self) -> Path:
        return self.engine.config.source or default_config_path()

    def profiles(self) -> dict[str, Any]:
        from ..install.state import InstallState

        root = project_root()
        hw = self.hardware
        listed = [
            {"name": p.name, "title": p.title, "description": p.description, "gpu": p.gpu,
             "llm_model": p.llm_model, "accelerator": profiles.accelerator(p, hw)}
            for p in profiles.PROFILES.values()
        ]  # fmt: skip
        path = self._config_path()
        if profiles.custom_path(path).exists():  # made with setup's Custom questions
            from ..install import custom
            from ..install.wizard import preview_config

            mine = profiles.get(profiles.CUSTOM, path)
            config = preview_config(path, profiles.CUSTOM, root / "config.example.toml" if root else path)
            listed.append({"name": mine.name, "title": "Custom", "gpu": mine.gpu, "llm_model": mine.llm_model,
                           "description": custom.describe(custom.defaults_from(config, hw)) + ". Change it with "
                           "`speakcheck setup`.", "accelerator": profiles.accelerator(mine, hw)})  # fmt: skip
        return {
            "current": self.engine.config.profile,
            "recommended": profiles.recommend(hw),
            "hardware": hw.summary(),
            "installed_accelerator": InstallState.load(root).accelerator if root else None,
            "config_path": str(path),
            "profiles": listed,
        }

    def set_profile(self, name: str) -> dict[str, Any]:
        """Switch profile now. Models load on next use; what can't happen here is listed in `needs`."""
        from ..install import ollama
        from ..install.download import plan_downloads
        from ..install.wizard import downloaded

        profile = profiles.get(name, self._config_path())
        if self.busy or self.engine.is_recording():
            raise SpeakcheckError("finish the current recording or analysis first")
        root = project_root()
        path = self._config_path()
        choose_profile(path, name, template=root / "config.example.toml" if root else None)
        self.engine.config = load_config(path)
        for kind in self.MODEL_KINDS:
            self.engine.release(kind)
        info = self.profiles()
        needs = []
        accelerator = profiles.accelerator(profile, self.hardware)
        # A GPU build also runs on the CPU; only the cpu build can't serve a GPU profile.
        if info["installed_accelerator"] == "cpu" and accelerator != "cpu":
            needs.append(f"This profile needs PyTorch for {accelerator}: run `speakcheck setup --profile {name}`.")
        for d in plan_downloads(self.engine.config):
            if d.source == "ollama" and "grammar" in self.engine.config.engine.analyzers and not ollama.has_model(d.name):
                needs.append(f"Grammar needs its model: run `ollama pull {d.name}`.")
            elif d.source != "ollama" and not downloaded(d):
                needs.append(f"{d.name} downloads on first use" + (f" (~{d.approx_gb:g} GB)." if d.approx_gb else "."))
        self.publish("settings_changed", settings=self.settings())
        return {**info, "needs": needs}

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
            if self._backend is not None and self._backend.remote:
                self._backend.practice_feed(Path(status["path"]))  # stream while the user speaks
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
            "engine": {"mode": self.engine.config.remote.mode, "url": self.engine.config.remote.url},
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
        self._reset_backend()
        if self._sync is not None:
            self._sync.stop()
            self._sync = None
        self.engine.close()

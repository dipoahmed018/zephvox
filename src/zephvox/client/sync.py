"""Background sync with a zephvox server: history backup and the offline queue.

- **Offline queue** (client mode): a recording made while the server was unreachable is kept as a
  session marked `pending.json` and analyzed as soon as the server answers again.
- **History** (when sync is on): sessions (result, feedback, audio) and practice attempts go to the
  server under this account, and sessions recorded on the account's other devices come back.
  The newest edit of a session wins; deleting one deletes it everywhere.

What has been synced is remembered in `<data_dir>/sync.json`.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..engine.engine import Engine
from ..engine.practice import PracticeAttempt
from ..engine.session import Session
from .remote import ServerClient, ServerError, ServerUnreachable

STATE_FILE = "sync.json"
PENDING_FILE = "pending.json"
INTERVAL_S = 60.0
OFFLINE_RETRY_S = 15.0
SAME = 0.01  # timestamps closer than this are the same version


@dataclass
class SyncState:
    cursor: float = 0.0  # the server's clock at the last pull
    attempts_cursor: float = 0.0
    known: dict[str, float] = field(default_factory=dict)  # session → version both sides have
    audio: list[str] = field(default_factory=list)  # sessions whose audio the server has
    attempts_pushed: int = 0  # practice log entries already sent

    @classmethod
    def load(cls, data_dir: Path) -> SyncState:
        try:
            data = json.loads((Path(data_dir) / STATE_FILE).read_text())
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, data_dir: Path) -> None:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        (Path(data_dir) / STATE_FILE).write_text(json.dumps(asdict(self)))


def mark_pending(session: Session, analyzers: list[str] | None) -> None:
    (session.dir / PENDING_FILE).write_text(json.dumps({"analyzers": analyzers, "since": time.time()}))


def pending(session: Session) -> dict[str, Any] | None:
    try:
        return json.loads((session.dir / PENDING_FILE).read_text())
    except (OSError, ValueError):
        return None


def version(session: Session) -> float:
    """When the session last changed here: its result or feedback file, whichever is newer."""
    times = [p.stat().st_mtime for p in (session.result_path, session.feedback_path) if p.exists()]
    return max(times, default=0.0)


class SyncWorker:
    def __init__(self, engine: Engine, client: Callable[[], ServerClient], history: bool,
                 analyze_pending: Callable[[Session, list[str] | None], Any] | None = None,
                 publish: Callable[..., None] = lambda type, **data: None):  # fmt: skip
        self.engine = engine
        self.client = client
        self.history = history  # sessions and practice too, not only the offline queue
        self.analyze_pending = analyze_pending
        self.publish = publish
        self.status: dict[str, Any] = {"last": None, "error": None, "offline": False, "storage_full": False}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def data_dir(self) -> Path:
        return self.engine.config.engine.data_dir

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)

    def trigger(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self._wake.wait(OFFLINE_RETRY_S if self.status["offline"] else INTERVAL_S)
            self._wake.clear()

    def run_once(self) -> dict[str, Any]:
        with self._lock:
            counts = {"analyzed": 0, "pushed": 0, "pulled": 0, "deleted": 0}
            client = self.client()
            state = SyncState.load(self.data_dir)
            try:
                if self.analyze_pending is not None:
                    counts["analyzed"] = self._drain_queue()
                if self.history:
                    self._push(client, state, counts)
                    self._pull(client, state, counts)
                    self._attempts(client, state)
                self.status.update(last=time.time(), error=None, offline=False)
            except ServerUnreachable as e:
                self.status.update(error=str(e), offline=True)
            except ServerError as e:
                self.status.update(error=str(e), offline=False)
            finally:
                state.save(self.data_dir)
                client.close()
            self.publish("sync", **self.status, **counts)
            if counts["pulled"] or counts["deleted"] or counts["analyzed"]:
                self.publish("sessions_changed")
            return counts

    # --- offline queue ------------------------------------------------------------------

    def _drain_queue(self) -> int:
        done = 0
        for session in self.engine.sessions.list():
            marker = pending(session)
            if marker is None or not session.audio_path.exists():
                continue
            self.analyze_pending(session, marker.get("analyzers"))  # type: ignore[misc]  # raises if still offline
            (session.dir / PENDING_FILE).unlink(missing_ok=True)
            done += 1
        return done

    # --- sessions -----------------------------------------------------------------------

    def _push(self, client: ServerClient, state: SyncState, counts: dict[str, int]) -> None:
        store = self.engine.sessions
        local = {s.id: s for s in store.list() if s.result_path.exists() and pending(s) is None}
        for sid in list(local):
            session = local[sid]
            updated = version(session)
            if abs(state.known.get(sid, -1) - updated) > SAME:
                result = json.loads(session.result_path.read_text())
                result["audio_path"] = ""
                feedback = json.loads(session.feedback_path.read_text()) if session.feedback_path.exists() else {}
                try:
                    client.put_session(sid, updated, result, feedback)
                except ServerError as e:
                    if e.status == 409 and "id_taken" in str(e):
                        session = self._rename(session)  # pushed under its new name next time
                        continue
                    if e.status == 409:  # edited more recently on another device: take that one
                        self._fetch(client, sid, None, state)
                        counts["pulled"] += 1
                        continue
                    if e.status == 507:
                        self.status["storage_full"] = True
                        break
                    raise
                state.known[sid] = updated
                counts["pushed"] += 1
            if sid not in state.audio and session.audio_path.exists() and not self.status["storage_full"]:
                try:
                    client.put_audio(sid, session.audio_path)
                    state.audio.append(sid)
                except ServerError as e:
                    if e.status != 507:
                        raise
                    self.status["storage_full"] = True
        for sid in [s for s in state.known if s not in local and not (store.root / s).exists()]:
            try:
                client.delete_session(sid, time.time())
            except ServerError as e:
                if e.status != 409:
                    raise
            state.known.pop(sid, None)
            if sid in state.audio:
                state.audio.remove(sid)

    def _pull(self, client: ServerClient, state: SyncState, counts: dict[str, int]) -> None:
        reply = client.sessions_since(state.cursor)
        store = self.engine.sessions
        for item in reply["sessions"]:
            sid = item["id"]
            folder = store.root / sid
            local_version = version(Session(sid, folder)) if folder.exists() else None
            if item["deleted"]:
                if folder.exists() and (local_version or 0) <= item["updated"] + SAME:
                    store.delete(Session(sid, folder))
                    counts["deleted"] += 1
                state.known.pop(sid, None)
                if sid in state.audio:
                    state.audio.remove(sid)
            elif local_version is None or local_version < item["updated"] - SAME:
                self._fetch(client, sid, item, state)
                counts["pulled"] += 1
        state.cursor = reply["now"]

    def _fetch(self, client: ServerClient, sid: str, item: dict[str, Any] | None, state: SyncState) -> None:
        data = client.get_session(sid)
        folder = self.engine.sessions.root / sid
        folder.mkdir(parents=True, exist_ok=True)
        session = Session(sid, folder)
        if data.get("has_audio") and not session.audio_path.exists():
            session.audio_path.write_bytes(client.get_audio(sid))
            state.audio.append(sid)
        result = {**data["result"], "session_id": sid, "audio_path": str(session.audio_path)}
        session.result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        session.feedback_path.write_text(json.dumps(data.get("feedback") or {}))
        updated = data["updated"]
        for path in (session.result_path, session.feedback_path):
            os.utime(path, (updated, updated))  # this version is now the same on both sides
        state.known[sid] = updated

    def _rename(self, session: Session) -> Session:
        """Two devices made sessions with the same id: this one gets a new, unique id."""
        new_id = f"{session.id}-{secrets.token_hex(2)}"
        new_dir = session.dir.with_name(new_id)
        session.dir.rename(new_dir)
        renamed = Session(new_id, new_dir)
        if renamed.result_path.exists():
            result = json.loads(renamed.result_path.read_text())
            result.update(session_id=new_id, audio_path=str(renamed.audio_path))
            renamed.result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return renamed

    # --- practice -----------------------------------------------------------------------

    def _attempts(self, client: ServerClient, state: SyncState) -> None:
        store = self.engine.practice_store
        local = store.attempts()
        fresh = local[state.attempts_pushed :]
        if fresh:
            client.push_attempts([{**a.to_dict(), "audio": None} for a in fresh])
        reply = client.pull_attempts(state.attempts_cursor)
        seen = {(a.at, a.target, a.score) for a in local}
        for data in reply["attempts"]:
            if (data.get("at"), data.get("target"), data.get("score")) not in seen:
                fields = {k: v for k, v in data.items() if k in PracticeAttempt.__dataclass_fields__}
                store.add(PracticeAttempt(**{**fields, "audio": None}))
        state.attempts_cursor = reply["now"]
        state.attempts_pushed = len(store.attempts())

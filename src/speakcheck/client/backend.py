"""Where analysis runs: on this computer (`LocalBackend`) or on a server (`RemoteBackend`).

Recording, sessions, history and the GUI are the same either way: a remote result is saved into
the local session, so every page keeps working on local files.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

from ..engine import audio
from ..engine.engine import Engine, Recording
from ..engine.errors import ProviderUnavailable, SpeakcheckError
from ..engine.models import AnalysisResult
from ..engine.practice import PracticeAttempt
from ..engine.session import Session
from . import credentials
from .remote import PracticeStream, ServerClient, ServerError

RELAYED = ("stage_started", "stage_finished", "progress", "warning", "provider_fallback")
TTS_CACHE = 256

Source = Session | Recording | Path | str


class LocalBackend:
    remote = False

    def __init__(self, engine: Engine):
        self.engine = engine
        self._tts: OrderedDict[tuple[str, str], bytes] = OrderedDict()

    def analyze(self, source: Source, analyzers: list[str] | None = None) -> AnalysisResult:
        try:
            return self.engine.analyze(source, analyzers)
        finally:
            self.engine.release("llm")  # an autostarted Ollama only lives during the job

    def practice_begin(self, target: str) -> None:
        pass

    def practice_feed(self, path: Path) -> None:
        pass

    def practice_cancel(self) -> None:
        pass

    def practice(self, target: str, recording: Recording, source_session: str | None) -> PracticeAttempt:
        return self.engine.practice(target, recording, source_session)

    def tts(self, text: str) -> bytes:
        provider = self.engine.provider("tts")
        key = (text, f"{provider.name}:{provider.settings.model_dump_json()}")  # a new voice gets new audio
        if key not in self._tts:
            self._tts[key] = provider.synthesize(text)
            while len(self._tts) > TTS_CACHE:
                self._tts.popitem(last=False)
        return self._tts[key]

    def voices(self) -> dict[str, Any]:
        provider = self.engine.provider("tts")
        caps = provider.capabilities()
        return {"provider": provider.name, "selected": caps.get("voice"), "voices": caps.get("voices", [])}

    def close(self) -> None:
        pass


class RemoteBackend:
    remote = True

    def __init__(self, engine: Engine, client: ServerClient):
        self.engine = engine
        self.client = client
        self._stream: PracticeStream | None = None
        self._tts: OrderedDict[tuple[str, str], bytes] = OrderedDict()

    def _session(self, source: Source) -> Session:
        if isinstance(source, Session):
            return source
        if isinstance(source, Recording):
            if source.session_id:
                return self.engine.sessions.get(source.session_id)
            source = Path(source.path)
        session = self.engine.sessions.create()
        audio.write_wav(session.audio_path, audio.decode(source))
        return session

    def analyze(self, source: Source, analyzers: list[str] | None = None) -> AnalysisResult:
        session = self._session(source)
        events = self.engine.events
        events.emit("stage_started", stage="upload")
        job = self.client.submit(session.audio_path, analyzers or self.engine.config.engine.analyzers,
                                 idempotency_key=f"{session.id}-{uuid.uuid4().hex}")  # fmt: skip
        events.emit("stage_finished", stage="upload")
        done = self.client.wait(job["id"], lambda e: e["type"] in RELAYED and events.emit(e["type"], **e["data"]))
        if done["status"] != "done":
            raise ServerError(f"the server couldn't analyze this recording: {done.get('error') or done['status']}")
        result = AnalysisResult.from_dict(done["result"])
        result.session_id = session.id
        result.audio_path = str(session.audio_path)
        result.providers = {**result.providers, "server": self.client.url}
        self.engine.sessions.save_result(session, result)
        for finding in result.findings:
            events.emit("finding", finding=finding)
        return result

    # --- practice -----------------------------------------------------------------------

    def _practice_stream(self) -> PracticeStream:
        if self._stream is None:
            self._stream = self.client.practice()
        return self._stream

    def practice_begin(self, target: str) -> None:
        self._practice_stream().begin(target)

    def practice_feed(self, path: Path) -> None:
        if self._stream is not None:
            self._stream.feed(path)

    def practice_cancel(self) -> None:
        if self._stream is not None:
            self._stream.cancel()

    def practice(self, target: str, recording: Recording, source_session: str | None) -> PracticeAttempt:
        stream = self._practice_stream()
        if stream._target != target:  # recorded without begin (e.g. the CLI): send it all now
            stream.begin(target)
        data = stream.end(Path(recording.path))
        attempt = PracticeAttempt(**{**data, "audio": recording.path, "source_session": source_session})
        self.engine.practice_store.add(attempt)
        self.engine.events.emit("practice_result", attempt=attempt.to_dict())
        return attempt

    # --- voices -------------------------------------------------------------------------

    def _voice(self) -> str | None:
        from ..engine.config import load_user_settings

        return (load_user_settings(self.engine.config.engine.data_dir).get("tts") or {}).get("voice")

    def tts(self, text: str) -> bytes:
        key = (text, self._voice() or "")
        if key not in self._tts:
            self._tts[key] = self.client.tts(text, key[1] or None)
            while len(self._tts) > TTS_CACHE:
                self._tts.popitem(last=False)
        return self._tts[key]

    def voices(self) -> dict[str, Any]:
        data = self.client.voices()
        return {"provider": "server", "selected": self._voice() or data.get("selected"), "voices": data.get("voices", [])}

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
        self.client.close()


def make_backend(engine: Engine) -> LocalBackend | RemoteBackend:
    """The backend the config asks for. Remote mode without a key is an error the user can act on."""
    remote = engine.config.remote
    if remote.mode != "remote":
        return LocalBackend(engine)
    if not remote.url:
        raise SpeakcheckError("client mode needs a server address: set it in the settings page or [remote] url")
    creds = credentials.load(engine.config.engine.data_dir, remote.url)
    if creds is None:
        raise ProviderUnavailable("server", [f"this device isn't connected to {remote.url} yet: redeem an invite"])
    return RemoteBackend(engine, ServerClient(remote.url, remote.headers, creds.key))


def client_for(engine: Engine, url: str | None = None, headers: dict[str, str] | None = None) -> ServerClient:
    """A client for the configured (or given) server, with this device's key if it has one."""
    remote = engine.config.remote
    url = url or remote.url
    if not url:
        raise SpeakcheckError("no server address configured")
    creds = credentials.load(engine.config.engine.data_dir, url)
    return ServerClient(url, remote.headers if headers is None else headers, creds.key if creds else None)

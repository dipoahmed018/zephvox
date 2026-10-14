"""Talking to a speakcheck server: invites, jobs (with live progress), practice streaming, voices."""

from __future__ import annotations

import json
import os
import re
import struct
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx

from ..engine.errors import SpeakcheckError

TIMEOUT_S = 30.0
UPLOAD_TIMEOUT_S = 600.0
POLL_S = 1.0
ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
FINAL = ("done", "failed", "cancelled")


class ServerError(SpeakcheckError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ServerUnreachable(ServerError):
    """The server can't be reached right now (offline, down, DNS): worth retrying later."""


class QueuedOffline(ServerUnreachable):
    """The recording is saved and will be analyzed when the server can be reached again."""


def expand_headers(headers: dict[str, str], env: dict[str, str] | None = None) -> dict[str, str]:
    """`${VAR}` in header values comes from the environment (.env), so secrets stay out of config.toml."""
    env = os.environ if env is None else env
    return {k: ENV_REF.sub(lambda m: env.get(m[1], ""), v) for k, v in headers.items()}


def is_insecure(url: str) -> bool:
    """Plain http to another machine: keys and recordings would cross the network unencrypted."""
    parts = httpx.URL(url)
    return parts.scheme == "http" and parts.host not in ("localhost", "127.0.0.1", "::1")


class ServerClient:
    def __init__(self, url: str, headers: dict[str, str] | None = None, key: str | None = None,
                 http: httpx.Client | None = None):  # fmt: skip
        self.url = url.rstrip("/")
        self.headers = expand_headers(headers or {})
        self.key = key
        self._own_http = http is None
        self._http = http or httpx.Client(base_url=self.url, timeout=TIMEOUT_S, follow_redirects=True)

    def close(self) -> None:
        if self._own_http:
            self._http.close()

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        out = dict(self.headers)
        if self.key:
            out["Authorization"] = f"Bearer {self.key}"
        return {**out, **(extra or {})}

    def request(self, method: str, path: str, *, headers: dict[str, str] | None = None, **kw: Any) -> httpx.Response:
        try:
            response = self._http.request(method, path, headers=self._headers(headers), **kw)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
            raise ServerUnreachable(f"can't reach the server at {self.url} ({type(e).__name__})") from e
        except httpx.HTTPError as e:
            raise ServerError(f"request to {self.url} failed: {e}") from e
        if response.status_code >= 400:
            raise ServerError(_detail(response), response.status_code)
        return response

    def _json(self, method: str, path: str, **kw: Any) -> Any:
        return self.request(method, path, **kw).json()

    # --- account ------------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        data = self._json("GET", "/v1/health")
        if data.get("service") != "speakcheck":
            raise ServerError(f"{self.url} doesn't look like a speakcheck server")
        return data

    def redeem(self, invite: str, device_name: str) -> dict[str, Any]:
        data = self._json("POST", "/v1/devices/redeem", json={"invite": invite.strip(), "device_name": device_name})
        self.key = data["key"]
        return data

    def account(self) -> dict[str, Any]:
        return self._json("GET", "/v1/account")

    def rotate(self) -> str:
        self.key = self._json("POST", "/v1/devices/me/rotate")["key"]
        return self.key  # type: ignore[return-value]

    def revoke(self, device_id: str) -> None:
        self.request("DELETE", f"/v1/devices/{device_id}")

    # --- jobs ---------------------------------------------------------------------------

    def submit(self, path: Path, analyzers: list[str] | None = None, idempotency_key: str | None = None,
               webhook_url: str | None = None) -> dict[str, Any]:  # fmt: skip
        data = {"analyzers": ",".join(analyzers or [])}
        if webhook_url:
            data["webhook_url"] = webhook_url
        with open(path, "rb") as f:
            return self._json("POST", "/v1/jobs", files={"audio": (Path(path).name, f, "audio/wav")}, data=data,
                              headers={"Idempotency-Key": idempotency_key or uuid.uuid4().hex},
                              timeout=UPLOAD_TIMEOUT_S)  # fmt: skip

    def job(self, job_id: str) -> dict[str, Any]:
        return self._json("GET", f"/v1/jobs/{job_id}")

    def events(self, job_id: str) -> Iterator[dict[str, Any]]:
        """Progress events until the job ends (the last one has type "job")."""
        try:
            with self._http.stream("GET", f"/v1/jobs/{job_id}/events", headers=self._headers(),
                                   timeout=httpx.Timeout(TIMEOUT_S, read=None)) as response:  # fmt: skip
                if response.status_code >= 400:
                    response.read()
                    raise ServerError(_detail(response), response.status_code)
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        yield json.loads(line[6:])
        except httpx.HTTPError as e:
            raise ServerUnreachable(f"lost the connection to {self.url} ({type(e).__name__})") from e

    def wait(self, job_id: str, on_event: Callable[[dict[str, Any]], None] = lambda e: None,
             sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:  # fmt: skip
        """Follow a job to the end and return it (with its result). Falls back to polling."""
        try:
            for event in self.events(job_id):
                if event["type"] == "job":
                    break
                on_event(event)
        except ServerUnreachable:
            pass  # the server may still finish it: poll
        while True:
            job = self.job(job_id)
            if job["status"] in FINAL:
                return job
            sleep(POLL_S)

    # --- practice and voices ------------------------------------------------------------

    def tts(self, text: str, voice: str | None = None) -> bytes:
        params = {"text": text, **({"voice": voice} if voice else {})}
        return self.request("GET", "/v1/tts", params=params).content

    def voices(self) -> dict[str, Any]:
        return self._json("GET", "/v1/voices")

    def practice(self) -> PracticeStream:
        return PracticeStream(self)

    # --- synced history -----------------------------------------------------------------

    def sessions_since(self, since: float) -> dict[str, Any]:
        return self._json("GET", "/v1/sessions", params={"since": since})

    def get_session(self, sid: str) -> dict[str, Any]:
        return self._json("GET", f"/v1/sessions/{sid}")

    def put_session(self, sid: str, updated: float, result: dict[str, Any], feedback: dict[str, str]) -> None:
        self.request("PUT", f"/v1/sessions/{sid}", json={"updated": updated, "result": result, "feedback": feedback})

    def put_audio(self, sid: str, path: Path) -> None:
        self.request("PUT", f"/v1/sessions/{sid}/audio", content=Path(path).read_bytes(),
                     headers={"Content-Type": "audio/wav"}, timeout=UPLOAD_TIMEOUT_S)  # fmt: skip

    def get_audio(self, sid: str) -> bytes:
        return self.request("GET", f"/v1/sessions/{sid}/audio", timeout=UPLOAD_TIMEOUT_S).content

    def delete_session(self, sid: str, updated: float) -> None:
        self.request("DELETE", f"/v1/sessions/{sid}", params={"updated": updated})

    def push_attempts(self, attempts: list[dict[str, Any]]) -> int:
        return self._json("POST", "/v1/practice/attempts", json={"attempts": attempts})["added"]

    def pull_attempts(self, since: float) -> dict[str, Any]:
        return self._json("GET", "/v1/practice/attempts", params={"since": since})


class PracticeStream:
    """One WebSocket for practice attempts: audio goes out while the user speaks, so only the
    scoring is left when they stop. If streaming breaks, the whole clip is sent at the end."""

    CHUNK = 6400  # 0.2 s of 16 kHz 16-bit audio

    def __init__(self, client: ServerClient):
        self.client = client
        self._ws: Any = None
        self._lock = threading.Lock()
        self._target: str | None = None
        self._sent = 0
        self._broken = False

    def _connect(self) -> Any:
        from websockets.sync.client import connect

        if self._ws is None:
            url = self.client.url.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/v1/practice"
            try:
                self._ws = connect(url, additional_headers=self.client._headers(), open_timeout=10, max_size=2**22)
            except OSError as e:
                raise ServerUnreachable(f"can't reach the server at {self.client.url} ({e})") from e
            except Exception as e:  # handshake refused (bad key, proxy)
                raise ServerError(f"the server refused the practice connection: {e}") from e
        return self._ws

    def _call(self, message: dict[str, Any]) -> dict[str, Any]:
        ws = self._connect()
        ws.send(json.dumps(message))
        return json.loads(ws.recv(timeout=60))

    def _drop(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # already gone
                pass
        self._ws = None

    def begin(self, target: str) -> None:
        with self._lock:
            self._target, self._sent, self._broken = target, 0, False
            try:
                reply = self._call({"type": "start", "target": target})
                if reply.get("type") != "started":
                    raise ServerError(reply.get("message", "the server didn't start the attempt"))
            except Exception:  # retried in one go at the end
                self._broken = True
                self._drop()

    def feed(self, path: Path) -> None:
        """Send the part of the growing recording that hasn't been sent yet."""
        with self._lock:
            if self._target is None or self._broken:
                return
            pcm = read_pcm(path)
            try:
                ws = self._connect()
                while self._sent + self.CHUNK <= len(pcm):
                    ws.send(pcm[self._sent : self._sent + self.CHUNK])
                    self._sent += self.CHUNK
            except Exception:
                self._broken = True
                self._drop()

    def end(self, path: Path) -> dict[str, Any]:
        """Finish the attempt and return the server's score (an attempt dict)."""
        with self._lock:
            target = self._target
            if target is None:
                raise ServerError("no practice attempt in progress")
            pcm = read_pcm(path)
            if not pcm:  # not 16 kHz mono 16-bit: convert, and send it all from the start
                pcm, self._broken = pcm_16k(path), True
            for attempt in range(2):
                try:
                    if self._broken or attempt:
                        self._drop()
                        if self._call({"type": "start", "target": target}).get("type") != "started":
                            raise ServerError("the server didn't start the attempt")
                        self._sent = 0
                    ws = self._connect()
                    for i in range(self._sent, len(pcm), self.CHUNK):
                        ws.send(pcm[i : i + self.CHUNK])
                    reply = self._call({"type": "end"})
                    break
                except ServerError:
                    raise
                except Exception as e:  # connection dropped mid-attempt: once more from the start
                    self._drop()
                    if attempt:
                        raise ServerUnreachable(f"lost the connection to {self.client.url} ({e})") from e
            self._target = None
            if reply.get("type") != "result":
                raise ServerError(reply.get("message", "the server couldn't score the attempt"))
            return reply["attempt"]

    def cancel(self) -> None:
        with self._lock:
            if self._target is not None and not self._broken and self._ws is not None:
                try:
                    self._call({"type": "cancel"})
                except Exception:
                    self._drop()
            self._target = None

    def close(self) -> None:
        with self._lock:
            self._drop()


def read_pcm(path: Path) -> bytes:
    """The 16 kHz mono 16-bit samples of a WAV file that may still be being written (sizes not final
    yet). Anything else (another rate, stereo, float) gives b"": `pcm_16k` converts it instead."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return b""
    if not data.startswith(b"RIFF"):
        return b""
    fmt = data.find(b"fmt ", 12, 4096)
    at = data.find(b"data", 12, 4096)
    if fmt < 0 or at < 0:
        return b""
    channels, rate = struct.unpack_from("<HI", data, fmt + 10)
    bits = struct.unpack_from("<H", data, fmt + 22)[0]
    if (channels, rate, bits) != (1, 16000, 16):
        return b""
    pcm = data[at + 8 :]
    return pcm[: len(pcm) // 2 * 2]


def pcm_16k(path: Path) -> bytes:
    """A finished recording as 16 kHz mono 16-bit PCM, whatever its format."""
    if pcm := read_pcm(path):
        return pcm
    import numpy as np

    from ..engine import audio

    samples = audio.decode(path)
    return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    return f"server said {response.status_code}: {detail or response.reason_phrase}"

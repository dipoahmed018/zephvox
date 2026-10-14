"""How the CLI finds and talks to a running daemon."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

DAEMON_FILE = "daemon.json"
DEFAULT_PORT = 8765


def daemon_file(data_dir: Path) -> Path:
    return Path(data_dir) / DAEMON_FILE


def write_daemon_file(data_dir: Path, url: str) -> None:
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    daemon_file(data_dir).write_text(json.dumps({"url": url, "pid": os.getpid()}))


def remove_daemon_file(data_dir: Path) -> None:
    daemon_file(data_dir).unlink(missing_ok=True)


def daemon_at(url: str, transport: httpx.BaseTransport | None = None) -> bool:
    """True if a zephvox daemon answers at this URL."""
    try:
        with httpx.Client(timeout=1.0, transport=transport) as client:
            client.get(f"{url}/api/settings").raise_for_status()
    except httpx.HTTPError:
        return False
    return True


def find_daemon(data_dir: Path, transport: httpx.BaseTransport | None = None) -> str | None:
    """URL of a live daemon for this data dir, or None."""
    try:
        info = json.loads(daemon_file(data_dir).read_text())
        url = info["url"]
    except (OSError, ValueError, KeyError):
        return None
    return url if daemon_at(url, transport) else None


def call(url: str, method: str, path: str, transport: httpx.BaseTransport | None = None, **kwargs: Any) -> Any:
    with httpx.Client(timeout=10.0, transport=transport) as client:
        resp = client.request(method, f"{url}{path}", **kwargs)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        raise DaemonError(detail)
    return resp.json()


class DaemonError(Exception):
    pass


# A custom header can't be sent by another website without a CORS preflight, which the daemon never
# answers: only local programs (this CLI) can ask it to quit.
QUIT_HEADER = {"X-Requested-With": "zephvox"}


def _terminate(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:
        os.kill(pid, signal.SIGTERM)


def stop_daemon(data_dir: Path, wait: float = 60.0, transport: httpx.BaseTransport | None = None,
                terminate: Callable[[int], None] = _terminate, sleep: Callable[[float], None] = time.sleep) -> str | None:  # fmt: skip
    """Stop the running daemon and wait until it is gone. Returns its URL, or None if none was running.

    It finishes the analysis it is in the middle of first (up to `wait` seconds)."""
    url = find_daemon(data_dir, transport)
    if url is None:
        return None
    try:
        call(url, "POST", "/api/quit", transport, headers=QUIT_HEADER)
    except DaemonError:
        # A daemon from before `quit` existed: it says who it is, and that process is ended instead.
        try:
            pid = int(call(url, "GET", "/api/status", transport)["pid"])
        except (DaemonError, httpx.HTTPError, KeyError, TypeError, ValueError):
            raise DaemonError("zephvox is running but doesn't answer to quit; close it from its terminal") from None
        terminate(pid)
    except httpx.HTTPError:
        pass  # it closed the connection while answering: it is going away
    deadline = time.monotonic() + wait
    while daemon_at(url, transport):
        if time.monotonic() >= deadline:
            raise DaemonError(f"zephvox didn't stop within {wait:g} s (it may still be analyzing a recording)")
        sleep(0.2)
    return url


def start_daemon(root: Path, data_dir: Path, wait: float = 30.0, popen: Callable[..., Any] = subprocess.Popen,
                 sleep: Callable[[float], None] = time.sleep) -> str | None:  # fmt: skip
    """Start `zephvox serve` in the background, detached from this terminal. Returns its URL once it
    answers, or None if it didn't come up in time."""
    flags: dict[str, Any] = (
        {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
        if os.name == "nt" else {"start_new_session": True})  # fmt: skip
    popen([sys.executable, "-m", "zephvox.cli", "serve"], cwd=root, stdin=subprocess.DEVNULL,
          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)  # fmt: skip
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if url := find_daemon(data_dir):
            return url
        sleep(0.5)
    return None

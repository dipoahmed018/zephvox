"""How the CLI finds and talks to a running daemon."""

from __future__ import annotations

import json
import os
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
    """True if a speakcheck daemon answers at this URL."""
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

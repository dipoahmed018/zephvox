"""This device's key for a server, in `<data_dir>/remote.json` (readable by the user only).

The key isn't kept in config.toml: it is written when an invite is redeemed and replaced when the
user asks for a new one.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

FILE = "remote.json"


@dataclass
class Credentials:
    url: str
    key: str
    device_id: str = ""
    device_name: str = ""
    account: str = ""


def same_server(a: str | None, b: str | None) -> bool:
    return bool(a and b) and a.rstrip("/") == b.rstrip("/")  # type: ignore[union-attr]


def load(data_dir: Path, url: str | None = None) -> Credentials | None:
    """The saved key; with `url`, only if it belongs to that server."""
    try:
        data = json.loads((Path(data_dir) / FILE).read_text(encoding="utf-8"))
        creds = Credentials(**{k: data.get(k, "") for k in Credentials.__dataclass_fields__})
    except (OSError, ValueError, TypeError):
        return None
    if not creds.key or (url is not None and not same_server(creds.url, url)):
        return None
    return creds


def save(data_dir: Path, creds: Credentials) -> None:
    path = Path(data_dir) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(asdict(creds), f, indent=2)
    os.replace(tmp, path)


def clear(data_dir: Path) -> None:
    (Path(data_dir) / FILE).unlink(missing_ok=True)

"""What setup installed (PyTorch build, extras, version), so `update` can install the same again."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..engine.errors import ZephvoxError

STATE_FILE = ".install.json"
BASE_EXTRAS = ("models", "desktop", "web", "voice")

Runner = Callable[..., subprocess.CompletedProcess]


class SetupError(ZephvoxError):
    pass


ROLES = ("full", "client")


def extras_for(accelerator: str | None, role: str = "full") -> list[str]:
    """full: everything (it can also serve other devices); client: record here, analyze on a server (no PyTorch)."""
    if role == "client":
        return ["desktop", "web"]
    return ["models", accelerator or "cpu", *BASE_EXTRAS[1:]]


@dataclass
class InstallState:
    accelerator: str | None = None
    extras: list[str] = field(default_factory=list)
    role: str | None = None  # full | client ("server" from older installs counts as full)
    version: str | None = None  # release installed by the bootstrap script or `update`

    @classmethod
    def load(cls, root: Path) -> InstallState:
        try:
            data = json.loads((root / STATE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self, root: Path) -> None:
        (root / STATE_FILE).write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")


def is_checkout(root: Path) -> bool:
    """A git working copy (a developer's), as opposed to an installed release."""
    return (root / ".git").exists()


def find_uv() -> str | None:
    if (uv := os.environ.get("UV")) and Path(uv).exists():  # set by `uv run`
        return uv
    if found := shutil.which("uv"):
        return found
    exe = "uv.exe" if os.name == "nt" else "uv"
    for candidate in (Path.home() / ".local" / "bin" / exe, Path.home() / ".cargo" / "bin" / exe):
        if candidate.exists():
            return str(candidate)
    return None


def sync_command(root: Path, extras: list[str], uv: str) -> list[str]:
    cmd = [uv, "sync", "--project", str(root)]
    for extra in extras:
        cmd += ["--extra", extra]
    if not is_checkout(root):
        cmd += ["--no-dev", "--frozen"]  # a release: test tools aren't needed, the lock is final
    return cmd


def sync(root: Path, extras: list[str], runner: Runner = subprocess.run) -> None:
    uv = find_uv()
    if uv is None:
        raise SetupError("uv not found: install it from https://docs.astral.sh/uv/ and run setup again")
    if runner(sync_command(root, extras, uv), check=False).returncode != 0:
        raise SetupError("installing the Python packages failed (see uv's message above)")

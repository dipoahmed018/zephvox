"""What setup installed (PyTorch build, extras, version), so `update` can install the same again."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..engine.errors import SpeakcheckError

STATE_FILE = ".install.json"
BASE_EXTRAS = ("models", "desktop", "web", "voice")

Runner = Callable[..., subprocess.CompletedProcess]


class SetupError(SpeakcheckError):
    pass


def extras_for(accelerator: str) -> list[str]:
    return ["models", accelerator, *BASE_EXTRAS[1:]]


@dataclass
class InstallState:
    accelerator: str | None = None
    extras: list[str] = field(default_factory=list)
    version: str | None = None  # release installed by the bootstrap script or `update`

    @classmethod
    def load(cls, root: Path) -> InstallState:
        try:
            data = json.loads((root / STATE_FILE).read_text())
        except (OSError, ValueError):
            return cls()
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self, root: Path) -> None:
        (root / STATE_FILE).write_text(json.dumps(asdict(self), indent=2) + "\n")


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

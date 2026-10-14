"""Ollama for setup: find or install it, and download the grammar model."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from ..engine.capabilities import which
from .state import Runner

HOST = "http://127.0.0.1:11434"
DOWNLOAD_PAGE = "https://ollama.com/download"


def find() -> str | None:
    return which("ollama")


def install_command(os_key: str, accelerator: str, has: Callable[[str], str | None] = shutil.which) -> list[str] | None:
    """The command that installs Ollama here, or None when the user has to download it."""
    if os_key == "win32" and has("winget"):
        return ["winget", "install", "--id", "Ollama.Ollama", "-e",
                "--accept-source-agreements", "--accept-package-agreements"]  # fmt: skip
    if os_key == "darwin" and has("brew"):
        return ["brew", "install", "ollama"]
    if os_key == "linux":
        if has("pacman"):  # Arch packages it per GPU backend
            package = {"cuda": "ollama-cuda", "rocm": "ollama-rocm"}.get(accelerator, "ollama")
            return ["sudo", "pacman", "-S", "--needed", package]
        if has("curl"):
            return ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"]
    return None


def models_dirs() -> list[Path]:
    if env := os.environ.get("OLLAMA_MODELS"):
        return [Path(env)]
    # Per user, and where Linux's system service (installed by Ollama's script) keeps them.
    return [Path.home() / ".ollama" / "models", Path("/usr/share/ollama/.ollama/models")]


def has_model(name: str, dirs: list[Path] | None = None) -> bool:
    """Whether `ollama pull name` already happened (checked on disk: works with Ollama stopped)."""
    model, _, tag = name.partition(":")
    parts = model.split("/") if "/" in model else ["library", model]
    for d in models_dirs() if dirs is None else dirs:
        if (d / "manifests" / "registry.ollama.ai" / Path(*parts) / (tag or "latest")).is_file():
            return True
    return False


def running(host: str = HOST) -> bool:
    try:
        return httpx.get(f"{host}/api/version", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


@contextmanager
def serving(binary: str, timeout: float = 60) -> Iterator[None]:
    """Make sure an Ollama server answers; stop it afterwards only if we started it."""
    if running():
        yield
        return
    proc = subprocess.Popen([binary, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + timeout
        while not running():
            if proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Ollama did not start")
            time.sleep(0.25)
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def pull(name: str, binary: str, runner: Runner = subprocess.run) -> bool:
    try:
        with serving(binary):
            return runner([binary, "pull", name], check=False).returncode == 0
    except RuntimeError:
        return False


def boot_service_enabled(runner: Runner = subprocess.run) -> bool:
    """Linux: Ollama's install script makes it start at boot; speakcheck only needs it on demand."""
    if not shutil.which("systemctl"):
        return False
    proc = runner(["systemctl", "is-enabled", "ollama"], capture_output=True, text=True, check=False)
    return proc.stdout.strip() == "enabled"

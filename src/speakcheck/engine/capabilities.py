"""What this machine can run. Providers consult this in `check_available()`."""

from __future__ import annotations

import ctypes
import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

KNOWN_BINARIES = ("ffmpeg", "pw-record", "espeak-ng")

# Where installers put programs that may not be on PATH (yet: a fresh install's PATH change only
# reaches new terminals).
EXTRA_BINARY_DIRS = {
    "espeak-ng": [Path(r"C:\Program Files\eSpeak NG"), Path(r"C:\Program Files (x86)\eSpeak NG")],
    "ollama": [Path(os.environ.get("LOCALAPPDATA", "~")) / "Programs" / "Ollama",
               Path("/Applications/Ollama.app/Contents/Resources"), Path("/opt/homebrew/bin"), Path("/usr/local/bin")],
}  # fmt: skip

# How to install a system package, per OS.
INSTALL = {
    "espeak-ng": {
        "linux": "sudo pacman -S espeak-ng  (Debian/Ubuntu: sudo apt install espeak-ng)",
        "darwin": "brew install espeak-ng",
        "win32": "install the .msi from https://github.com/espeak-ng/espeak-ng/releases",
    },
    "ffmpeg": {
        "linux": "sudo pacman -S ffmpeg  (Debian/Ubuntu: sudo apt install ffmpeg)",
        "darwin": "brew install ffmpeg",
        "win32": "winget install ffmpeg",
    },
    "ollama": {
        "linux": "sudo pacman -S ollama-rocm / ollama-cuda / ollama  (others: https://ollama.com/download)",
        "darwin": "brew install ollama  (or https://ollama.com/download)",
        "win32": "winget install Ollama.Ollama",
    },
}


def platform_key() -> str:
    return "linux" if sys.platform.startswith("linux") else sys.platform


def install_hint(package: str) -> str:
    return INSTALL.get(package, {}).get(platform_key(), f"install {package}")


@dataclass(frozen=True)
class GPUInfo:
    backend: str  # "rocm" | "cuda" | "mps"
    name: str
    vram_gb: float


@dataclass
class SystemCapabilities:
    gpu: GPUInfo | None = None
    ram_gb: float = 0.0
    binaries: dict[str, bool] = field(default_factory=dict)
    env_keys: frozenset[str] = frozenset()

    def has_binary(self, name: str) -> bool:
        if name not in self.binaries:
            self.binaries[name] = which(name) is not None
        return self.binaries[name]

    @staticmethod
    def has_module(name: str) -> bool:
        return importlib.util.find_spec(name) is not None

    def setup_hints(self) -> list[str]:
        """What to install so more drivers work on this machine (empty when nothing is missing)."""
        hints = []
        accelerator = detect_accelerator()
        if not self.has_module("torch"):
            hints.append(f"speech models: uv sync --extra models --extra {accelerator}  (plus desktop, web, voice)")
        elif self.gpu is None and accelerator != "cpu":
            if accelerator == "rocm":
                hints.append("PyTorch can't see the AMD GPU: add HSA_OVERRIDE_GFX_VERSION to .env "
                             "(e.g. 10.3.0 for RX 6000) and check you're in the render/video groups")  # fmt: skip
            else:
                hints.append(f"PyTorch can't see the GPU: reinstall with `uv sync --extra models --extra {accelerator}`")
        # espeak-ng comes bundled with the models extra; a system copy is only a fallback.
        if self.has_module("torch") and not self.has_module("espeakng_loader") and not self.has_binary("espeak-ng"):
            hints.append(f"espeak-ng: {install_hint('espeak-ng')}")
        if not self.has_module("av") and not self.has_binary("ffmpeg"):  # PyAV comes with the models extra
            hints.append(f"ffmpeg (audio files other than WAV): {install_hint('ffmpeg')}")
        if not self.has_binary("ollama"):
            hints.append(f"ollama (grammar): {install_hint('ollama')}, then `ollama pull qwen3:8b`")
        return hints

    def to_dict(self) -> dict:
        return {
            "gpu": None if self.gpu is None else vars(self.gpu),
            "ram_gb": round(self.ram_gb, 1),
            "binaries": dict(self.binaries),
            "env_keys": sorted(self.env_keys),
            "platform": platform_key(),
        }


def which(name: str) -> str | None:
    """`shutil.which`, plus the folders installers use without adding them to PATH."""
    if found := shutil.which(name):
        return found
    for d in EXTRA_BINARY_DIRS.get(name, []):
        if found := shutil.which(name, path=str(d)):
            return found
    return None


def detect_accelerator() -> str:
    """Which PyTorch build suits this machine: 'cuda', 'rocm' or 'cpu' (also right for macOS)."""
    from .hardware import accelerator_for, detect_gpus  # hardware builds on this module

    return accelerator_for(detect_gpus(detect_ram_gb()))


def detect_gpu() -> GPUInfo | None:
    if importlib.util.find_spec("torch") is None:
        return None
    try:
        import torch

        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            backend = "rocm" if getattr(torch.version, "hip", None) else "cuda"
            return GPUInfo(backend, torch.cuda.get_device_name(0), props.total_memory / 1e9)
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        if mps is not None and mps.is_available():
            return GPUInfo("mps", "Apple GPU", detect_ram_gb())  # memory is shared with the CPU
        return None
    except Exception:  # a broken GPU stack must never break the engine
        return None


def detect_ram_gb(meminfo: Path = Path("/proc/meminfo")) -> float:
    try:
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return _ram_from_os() if meminfo == Path("/proc/meminfo") else 0.0


def _ram_from_os() -> float:
    try:
        if sys.platform == "win32":

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]  # fmt: skip

            status = MemoryStatus(dwLength=ctypes.sizeof(MemoryStatus))
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.ullTotalPhys / 1024**3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3  # macOS, BSD
    except (AttributeError, OSError, ValueError):
        return 0.0


def detect(probe_gpu: bool = True) -> SystemCapabilities:
    keys = frozenset(k for k in os.environ if k.endswith(("_API_KEY", "_TOKEN")))
    caps = SystemCapabilities(
        gpu=detect_gpu() if probe_gpu else None,
        ram_gb=detect_ram_gb(),
        env_keys=keys,
    )
    for name in KNOWN_BINARIES:
        caps.has_binary(name)
    return caps

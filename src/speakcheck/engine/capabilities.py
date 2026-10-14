"""What this machine can run. Providers consult this in `check_available()`."""

from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

KNOWN_BINARIES = ("ffmpeg", "pw-record", "espeak-ng")


@dataclass(frozen=True)
class GPUInfo:
    backend: str  # "rocm" | "cuda"
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
            self.binaries[name] = shutil.which(name) is not None
        return self.binaries[name]

    @staticmethod
    def has_module(name: str) -> bool:
        return importlib.util.find_spec(name) is not None

    def to_dict(self) -> dict:
        return {
            "gpu": None if self.gpu is None else vars(self.gpu),
            "ram_gb": round(self.ram_gb, 1),
            "binaries": dict(self.binaries),
            "env_keys": sorted(self.env_keys),
        }


def detect_gpu() -> GPUInfo | None:
    if importlib.util.find_spec("torch") is None:
        return None
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        props = torch.cuda.get_device_properties(0)
        backend = "rocm" if getattr(torch.version, "hip", None) else "cuda"
        return GPUInfo(backend, torch.cuda.get_device_name(0), props.total_memory / 1e9)
    except Exception:  # a broken GPU stack must never break the engine
        return None


def detect_ram_gb(meminfo: Path = Path("/proc/meminfo")) -> float:
    try:
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
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

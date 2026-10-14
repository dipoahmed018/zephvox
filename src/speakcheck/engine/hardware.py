"""What this machine has: CPU, RAM, GPUs, free disk. Works before PyTorch is installed.

`speakcheck setup` uses it to pick a profile and a PyTorch build. Every probe is best effort: a
missing tool or an unexpected output means "not detected", never an error.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .capabilities import detect_ram_gb, platform_key

AMD_VENDOR_ID = "0x1002"
MIN_GPU_VRAM_GB = 2.0  # below this it's an integrated GPU with a small carve-out: not useful


@dataclass(frozen=True)
class GPU:
    vendor: str  # "nvidia" | "amd" | "apple" | "other"
    name: str
    vram_gb: float | None
    backend: str | None  # PyTorch backend that can drive it here: "cuda" | "rocm" | "mps" | None
    gfx: str | None = None  # AMD architecture, e.g. "gfx1030"


@dataclass
class Hardware:
    os: str  # "linux" | "win32" | "darwin"
    arch: str
    cpu: str
    cores: int
    ram_gb: float
    disk_free_gb: float
    gpus: list[GPU] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # things to fix for the GPU to work

    @property
    def gpu(self) -> GPU | None:
        """The GPU speakcheck would use: the usable one with the most memory."""
        return best_gpu(self.gpus)

    @property
    def accelerator(self) -> str:
        return accelerator_for(self.gpus)

    def summary(self) -> list[str]:
        gpus = [f"{g.name}" + (f", {g.vram_gb:.0f} GB" if g.vram_gb else "") +
                ("" if g.backend else " (not usable for speech models here)") for g in self.gpus]  # fmt: skip
        return [
            f"System: {self.os} {self.arch}",
            f"CPU:    {self.cpu} ({self.cores} threads)",
            f"RAM:    {self.ram_gb:.0f} GB",
            f"GPU:    {'; '.join(gpus) if gpus else 'none detected'}",
            f"Disk:   {self.disk_free_gb:.0f} GB free",
        ]


def best_gpu(gpus: list[GPU]) -> GPU | None:
    usable = [g for g in gpus if g.backend]
    return max(usable, key=lambda g: g.vram_gb or 0.0, default=None)


def accelerator_for(gpus: list[GPU]) -> str:
    """The PyTorch build to install: "cuda", "rocm" or "cpu" (macOS: the cpu build drives MPS)."""
    gpu = best_gpu(gpus)
    return gpu.backend if gpu and gpu.backend in ("cuda", "rocm") else "cpu"


def run(cmd: list[str], timeout: float = 15) -> str | None:
    """stdout of a successful command, else None."""
    if shutil.which(cmd[0]) is None:
        return None
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


# --- GPUs -------------------------------------------------------------------------------


def nvidia_gpus(output: str | None = None) -> list[GPU]:
    if output is None:
        output = run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    gpus = []
    for line in (output or "").splitlines():
        name, _, mib = line.rpartition(",")
        try:
            vram = float(mib) / 1024
        except ValueError:
            continue
        gpus.append(GPU("nvidia", name.strip(), round(vram, 1), "cuda"))
    return gpus


def amd_gpus(drm: Path = Path("/sys/class/drm"), rocminfo: str | None = None) -> list[GPU]:
    """AMD GPUs on Linux, from sysfs (needs no ROCm install: PyTorch's ROCm wheels bundle it)."""
    if rocminfo is None:
        rocminfo = run(["rocminfo"]) or ""
    agents = rocm_gpu_agents(rocminfo)
    gpus = []
    for card in sorted(drm.glob("card[0-9]*")):
        device = card / "device"
        try:
            if (device / "vendor").read_text().strip() != AMD_VENDOR_ID:
                continue
            vram = int((device / "mem_info_vram_total").read_text()) / 1024**3
        except (OSError, ValueError):
            continue
        if vram < MIN_GPU_VRAM_GB:
            continue
        name, arch = agents[len(gpus)] if len(gpus) < len(agents) else ("AMD GPU", None)
        x86 = platform.machine().lower() in ("x86_64", "amd64")
        gpus.append(GPU("amd", name, round(vram, 1), "rocm" if x86 else None, arch))
    return gpus


def rocm_gpu_agents(rocminfo: str) -> list[tuple[str, str]]:
    """(marketing name, gfx) of each discrete GPU agent in `rocminfo` output, in order.

    Integrated GPUs are reported under the CPU's name; they are skipped, as sysfs skips them by VRAM.
    """
    agents = []
    for block in re.split(r"^Agent \d+", rocminfo, flags=re.M)[1:]:
        kind = re.search(r"Device Type:\s*(\w+)", block)
        gfx = re.search(r"^\s{2}Name:\s*(gfx\w+)", block, flags=re.M)
        name = re.search(r"Marketing Name:\s*(.+?)\s*$", block, flags=re.M)
        if not (kind and kind.group(1) == "GPU" and gfx):
            continue
        label = name.group(1) if name else "AMD GPU"
        if "Processor" in label:  # an APU's integrated GPU
            continue
        agents.append((label, gfx.group(1)))
    return agents


def apple_gpu(ram_gb: float) -> GPU | None:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return None
    chip = (run(["sysctl", "-n", "machdep.cpu.brand_string"]) or "Apple Silicon").strip()
    return GPU("apple", f"{chip} GPU", round(ram_gb, 1), "mps")  # memory is shared with the CPU


def windows_other_gpus() -> list[GPU]:
    """Non-NVIDIA GPUs on Windows: listed for the summary; PyTorch can't use them here."""
    out = run(["powershell", "-NoProfile", "-Command",
               "(Get-CimInstance Win32_VideoController).Name"])  # fmt: skip
    return [GPU("other", n.strip(), None, None) for n in (out or "").splitlines()
            if n.strip() and "NVIDIA" not in n]  # fmt: skip


def detect_gpus(ram_gb: float) -> list[GPU]:
    gpus = nvidia_gpus()
    if sys.platform.startswith("linux"):
        gpus += amd_gpus()
    elif sys.platform == "win32":
        gpus += windows_other_gpus()
    elif (apple := apple_gpu(ram_gb)) is not None:
        gpus.append(apple)
    return gpus


# --- CPU, disk, notes -------------------------------------------------------------------


def cpu_name() -> str:
    if sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    elif sys.platform == "darwin":
        if out := run(["sysctl", "-n", "machdep.cpu.brand_string"]):
            return out.strip()
    return platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "") or platform.machine()


def disk_free_gb(path: Path) -> float:
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        return shutil.disk_usage(path).free / 1024**3
    except OSError:
        return 0.0


def gpu_notes(gpus: list[GPU]) -> list[str]:
    notes = []
    if any(g.vendor == "amd" and g.backend for g in gpus) and not os.access("/dev/kfd", os.R_OK | os.W_OK):
        notes.append("Your user can't access the AMD GPU yet: run `sudo usermod -aG render,video $USER`, "
                     "then log out and back in.")  # fmt: skip
    return notes


def detect(path: Path | None = None) -> Hardware:
    ram = detect_ram_gb()
    gpus = detect_gpus(ram)
    return Hardware(
        os=platform_key(),
        arch=platform.machine(),
        cpu=cpu_name(),
        cores=os.cpu_count() or 1,
        ram_gb=ram,
        disk_free_gb=disk_free_gb(path or Path.home()),
        gpus=gpus,
        notes=gpu_notes(gpus),
    )


def hsa_override(gfx: str | None) -> str | None:
    """HSA_OVERRIDE_GFX_VERSION that makes ROCm treat a consumer AMD GPU as a supported sibling."""
    if not gfx:
        return None
    if gfx.startswith("gfx103"):
        return "10.3.0"  # RX 6000
    if gfx.startswith("gfx110"):
        return "11.0.0"  # RX 7000
    if gfx.startswith("gfx120"):
        return "12.0.0"  # RX 9000
    return None

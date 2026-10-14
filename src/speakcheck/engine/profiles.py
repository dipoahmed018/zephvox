"""Profiles: named sets of settings sized to a machine. `speakcheck setup` recommends one.

A profile is just a config layer:

    built-in defaults  <  profile  <  config.toml  <  GUI settings  <  --set flags

so `profile = "small"` in config.toml changes model choices, and anything the user sets in
config.toml still wins. Thresholds are first estimates, to be tuned on real machines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import ConfigError
from .hardware import Hardware


@dataclass(frozen=True)
class Profile:
    name: str
    title: str
    description: str
    gpu: bool  # GPU tiers install the GPU build of PyTorch; CPU tiers the small cpu build
    overlay: dict[str, Any] = field(default_factory=dict)

    @property
    def llm_model(self) -> str | None:
        if "grammar" not in self.overlay.get("engine", {}).get("analyzers", ["grammar"]):
            return None
        return self.overlay.get("provider", {}).get("openai-compat", {}).get("model", "qwen3:8b")


def _llm(model: str) -> dict[str, Any]:
    return {"openai-compat": {"model": model}}


CPU_STT = {"stt": ["faster-whisper", "hf-whisper"]}

PROFILES: dict[str, Profile] = {p.name: p for p in [
    Profile("large", "Large GPU", "GPU with 16 GB+ (or a Mac with 32 GB+): the most accurate grammar model.",
            True, {"provider": _llm("qwen3:14b")}),
    Profile("standard", "Standard GPU", "GPU with 10–16 GB (or a Mac with 16 GB+).", True, {}),
    Profile("small", "Small GPU", "GPU with 6–10 GB (or a Mac with 8 GB): a smaller grammar model.",
            True, {"provider": _llm("qwen3:4b")}),
    Profile("cpu", "CPU", "No usable GPU, 16 GB+ RAM. Works, but each analysis takes longer.",
            False, {"providers": CPU_STT,
                    "provider": {**_llm("qwen3:4b"), "wav2vec2": {"device": "cpu"}}}),
    Profile("cpu-light", "CPU, light", "Under 16 GB RAM: pronunciation only, smaller speech model. "
            "Grammar can be turned on with a cloud LLM.",
            False, {"providers": CPU_STT, "engine": {"analyzers": ["pronunciation"]},
                    "provider": {"faster-whisper": {"model": "base.en"}, "wav2vec2": {"device": "cpu"}}}),
]}  # fmt: skip


def get(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        raise ConfigError(f"Unknown profile {name!r}; choose one of: {', '.join(PROFILES)}") from None


def recommend(hw: Hardware) -> str:
    gpu = hw.gpu
    if gpu is not None and gpu.vendor == "apple":
        return "large" if hw.ram_gb >= 30 else "standard" if hw.ram_gb >= 15 else "small"
    if gpu is not None and gpu.vram_gb:
        # Reported sizes run a little under the label (a "16 GB" card shows 15.98).
        if gpu.vram_gb >= 15:
            return "large"
        if gpu.vram_gb >= 9.5:
            return "standard"
        if gpu.vram_gb >= 5.5:
            return "small"
    return "cpu" if hw.ram_gb >= 14 else "cpu-light"


def accelerator(profile: Profile, hw: Hardware) -> str:
    """PyTorch build for this profile on this machine."""
    return hw.accelerator if profile.gpu else "cpu"


# Approximate (download, on disk) GB of the Python packages, by OS and PyTorch build.
PACKAGES_GB = {
    ("linux", "rocm"): (6.8, 16.0),
    ("linux", "cuda"): (3.9, 8.0),
    ("linux", "cpu"): (0.5, 1.5),
    ("win32", "cuda"): (2.8, 6.0),
    ("win32", "cpu"): (0.3, 1.2),
    ("darwin", "cpu"): (0.3, 1.0),
}


def packages_gb(os_key: str, accel: str) -> tuple[float, float]:
    return PACKAGES_GB.get((os_key, accel), (1.0, 3.0))

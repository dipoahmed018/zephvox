"""Fetch the speech models the configured drivers will use, ahead of the first analysis.

Run as `python -m speakcheck.install.download --config config.toml`: setup starts it in a fresh
process, after installing the packages it imports.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ..engine.config import Config, load_config
from ..engine.registry import Registry
from ..providers.base import Download

# The stages whose drivers download models.
MODEL_KINDS = ("stt", "phonemes", "tts", "llm")


def plan_downloads(config: Config, registry: Registry | None = None) -> list[Download]:
    """What the first-choice driver of each stage will download. Needs no model packages."""
    registry = registry or Registry()
    found = []
    for kind in MODEL_KINDS:
        names = [n for n in config.providers.get(kind, []) if n in registry.names(kind)]
        if names:
            cls = registry.get(kind, names[0])
            found += cls(config.provider_settings(names[0])).downloads()
    return found


def hf_cache_dir() -> Path:
    if env := os.environ.get("HF_HUB_CACHE"):
        return Path(env)
    return Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"


def repo_id(download: Download) -> str | None:
    """The Hugging Face repo a download lives in (faster-whisper names map to Systran's)."""
    if download.source == "huggingface":
        return download.name
    if download.source == "faster-whisper":
        return download.name if "/" in download.name else f"Systran/faster-whisper-{download.name}"
    return None


def cache_path(download: Download) -> Path | None:
    repo = repo_id(download)
    return hf_cache_dir() / f"models--{repo.replace('/', '--')}" if repo else None


def fetch(download: Download) -> None:
    if download.source == "huggingface":
        from huggingface_hub import snapshot_download

        snapshot_download(download.name, allow_patterns=list(download.patterns) if download.patterns else None)
    elif download.source == "faster-whisper":
        from faster_whisper import download_model

        download_model(download.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m speakcheck.install.download")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    for download in plan_downloads(load_config(args.config)):
        if download.source == "ollama":
            continue  # setup pulls it with the ollama program
        size = f" (~{download.approx_gb:g} GB)" if download.approx_gb else ""
        print(f"Downloading {download.name}{size}", flush=True)
        try:
            fetch(download)
        except Exception as e:  # report and keep going: the driver retries on first use
            print(f"  failed: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

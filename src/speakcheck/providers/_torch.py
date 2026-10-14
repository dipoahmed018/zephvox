"""Helpers for torch-based providers. Imported lazily — never at plugin load time."""

from __future__ import annotations


def quiet_transformers() -> None:
    """Silence transformers/hub progress bars and advisory warnings; real errors still raise."""
    import os

    # transformers otherwise fetches a converted .safetensors copy of .bin-only models (wav2vec2)
    # in the background: a second download of the same weights.
    os.environ.setdefault("DISABLE_SAFETENSORS_CONVERSION", "1")
    from huggingface_hub.utils import disable_progress_bars
    from huggingface_hub.utils import logging as hub_logging
    from transformers.utils import logging

    logging.set_verbosity_error()
    logging.disable_progress_bar()
    disable_progress_bars()
    hub_logging.set_verbosity_error()


def resolve_device(setting: str) -> str:
    """'auto' → first GPU (ROCm or CUDA; both appear as 'cuda' in torch), Apple GPU, else CPU."""
    if setting != "auto":
        return setting
    import torch

    if torch.cuda.is_available():
        return "cuda:0"
    return "mps" if torch.backends.mps.is_available() else "cpu"

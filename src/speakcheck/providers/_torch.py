"""Helpers for torch-based providers. Imported lazily — never at plugin load time."""

from __future__ import annotations


def quiet_transformers() -> None:
    """Silence transformers/hub progress bars and advisory warnings; real errors still raise."""
    from huggingface_hub.utils import disable_progress_bars
    from huggingface_hub.utils import logging as hub_logging
    from transformers.utils import logging

    logging.set_verbosity_error()
    logging.disable_progress_bar()
    disable_progress_bars()
    hub_logging.set_verbosity_error()


def resolve_device(setting: str) -> str:
    """'auto' → first GPU (ROCm or CUDA; both appear as 'cuda' in torch) else CPU."""
    if setting != "auto":
        return setting
    import torch

    return "cuda:0" if torch.cuda.is_available() else "cpu"

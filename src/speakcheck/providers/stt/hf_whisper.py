"""Whisper through Hugging Face transformers — runs on ROCm, CUDA or CPU via PyTorch."""

from __future__ import annotations

import importlib.util
from typing import Any

import numpy as np

from ...engine.models import Segment, Transcript, Word
from .._torch import quiet_transformers, resolve_device
from ..base import Availability, ProviderSettings, STTProvider


class HFWhisperSTT(STTProvider):
    name = "hf-whisper"

    class Settings(ProviderSettings):
        model: str = "openai/whisper-large-v3-turbo"
        device: str = "auto"
        language: str = "en"
        chunk_length_s: int = 30
        batch_size: int = 8

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._pipe = None

    def check_available(self) -> Availability:
        for module in ("torch", "transformers"):
            if importlib.util.find_spec(module) is None:
                return Availability(False, f"python package {module!r} not installed (uv sync --extra models)")
        return Availability(True)

    def capabilities(self) -> dict[str, Any]:
        return {"word_timestamps": True, "verbatim": "none", "languages": ["multi"], "gpu": True}

    def _load(self):
        if self._pipe is None:
            import torch
            from transformers import pipeline

            quiet_transformers()
            device = resolve_device(self.settings.device)
            self._pipe = pipeline(
                "automatic-speech-recognition",
                model=self.settings.model,
                dtype=torch.float16 if device != "cpu" else torch.float32,
                device=device,
            )
        return self._pipe

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> Transcript:
        pipe = self._load()
        kwargs = {}
        if len(samples) > self.settings.chunk_length_s * sample_rate:
            # Only long recordings need the pipeline's chunked mode.
            kwargs = {"chunk_length_s": self.settings.chunk_length_s, "batch_size": self.settings.batch_size}
        out = pipe(
            {"raw": samples, "sampling_rate": sample_rate},
            return_timestamps="word",
            generate_kwargs={"language": self.settings.language, "task": "transcribe"},
            **kwargs,
        )
        words = []
        for chunk in out.get("chunks", []):
            start, end = chunk["timestamp"]
            if start is None:
                continue
            words.append(Word(chunk["text"].strip(), float(start), float(end if end is not None else start)))
        text = out.get("text", "").strip()
        if not words:
            return Transcript([], provider=self.name)
        segment = Segment(text=text, start=words[0].start, end=words[-1].end, words=words)
        return Transcript([segment], language=self.settings.language, provider=self.name, verbatim="none")

    def close(self) -> None:
        self._pipe = None

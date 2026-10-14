"""Whisper through Hugging Face transformers — runs on ROCm, CUDA or CPU via PyTorch."""

from __future__ import annotations

import importlib.util
from typing import Any

import numpy as np

from ...engine import audio
from ...engine.models import Segment, Transcript, Word
from .._torch import quiet_transformers, resolve_device
from ..base import Availability, Download, ProviderSettings, STTProvider


APPROX_GB = {
    "openai/whisper-large-v3-turbo": 1.6,
    "openai/whisper-large-v3": 3.1,
    "openai/whisper-medium.en": 1.5,
    "openai/whisper-small.en": 0.5,
    "distil-whisper/distil-large-v3": 1.5,
}


class HFWhisperSTT(STTProvider):
    name = "hf-whisper"

    class Settings(ProviderSettings):
        model: str = "openai/whisper-large-v3-turbo"
        device: str = "auto"
        language: str = "en"
        # Whisper works on 30 s windows. Longer audio is split at quiet moments into pieces of at
        # most this length; transformers' own long-form mode uses runaway memory with word timestamps.
        max_piece_s: float = 28.0

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._pipe = None

    def check_available(self) -> Availability:
        for module in ("torch", "transformers"):
            if importlib.util.find_spec(module) is None:
                return Availability(False, f"python package {module!r} not installed (uv sync --extra models --extra cpu|cuda|rocm)")
        return Availability(True)

    def downloads(self) -> list[Download]:
        model = self.settings.model
        return [Download("huggingface", model, APPROX_GB.get(model), ("*.json", "*.txt", "*.safetensors"))]

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
        words: list[Word] = []
        texts: list[str] = []
        for offset, piece in audio.split_on_silence(samples, self.settings.max_piece_s, sample_rate=sample_rate):
            out = pipe(
                {"raw": piece, "sampling_rate": sample_rate},
                return_timestamps="word",
                generate_kwargs={"language": self.settings.language, "task": "transcribe"},
            )
            texts.append(out.get("text", "").strip())
            for chunk in out.get("chunks", []):
                start, end = chunk["timestamp"]
                if start is None:
                    continue
                end = end if end is not None else start
                words.append(Word(chunk["text"].strip(), offset + float(start), offset + float(end)))
        if not words:
            return Transcript([], provider=self.name)
        text = " ".join(t for t in texts if t)
        segment = Segment(text=text, start=words[0].start, end=words[-1].end, words=words)
        return Transcript([segment], language=self.settings.language, provider=self.name, verbatim="none")

    def close(self) -> None:
        self._pipe = None

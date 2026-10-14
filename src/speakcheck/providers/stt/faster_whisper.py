"""Whisper through faster-whisper (CTranslate2). Fast on CPU; GPU only with CUDA."""

from __future__ import annotations

import importlib.util
from typing import Any

import numpy as np

from ...engine.models import Segment, Transcript, Word
from ..base import Availability, Download, ProviderSettings, STTProvider

# Priming Whisper with disfluent text makes it keep fillers and false starts instead of
# tidying them away — which also makes it less likely to silently fix grammar.
DISFLUENT_PROMPT = "Umm, let me think like, hmm... Okay, here's what I'm, like, thinking."


class FasterWhisperSTT(STTProvider):
    name = "faster-whisper"

    class Settings(ProviderSettings):
        model: str = "small.en"
        device: str = "cpu"
        compute_type: str = "int8"
        beam_size: int = 5
        vad_filter: bool = True
        initial_prompt: str | None = DISFLUENT_PROMPT

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._model = None

    def check_available(self) -> Availability:
        if importlib.util.find_spec("faster_whisper") is None:
            return Availability(False, "python package 'faster_whisper' not installed (uv sync --extra models)")
        return Availability(True)

    def downloads(self) -> list[Download]:
        approx = {"base.en": 0.15, "small.en": 0.5, "medium.en": 1.5, "large-v3": 3.1}.get(self.settings.model)
        return [Download("faster-whisper", self.settings.model, approx)]

    def capabilities(self) -> dict[str, Any]:
        verbatim = "partial" if self.settings.initial_prompt else "none"
        return {"word_timestamps": True, "verbatim": verbatim, "languages": ["en"], "gpu": False}

    def transcribe(self, samples: np.ndarray, sample_rate: int) -> Transcript:
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.settings.model, device=self.settings.device, compute_type=self.settings.compute_type
            )
        segments_iter, _info = self._model.transcribe(
            samples,
            language="en",
            beam_size=self.settings.beam_size,
            word_timestamps=True,
            vad_filter=self.settings.vad_filter,
            initial_prompt=self.settings.initial_prompt,
            condition_on_previous_text=False,
        )
        segments = []
        for seg in segments_iter:
            words = [Word(w.word.strip(), w.start, w.end, w.probability) for w in (seg.words or [])]
            segments.append(Segment(seg.text.strip(), seg.start, seg.end, words))
        return Transcript(segments, provider=self.name, verbatim=self.capabilities()["verbatim"])

    def close(self) -> None:
        self._model = None

"""Pronunciations for words no dictionary has (names, brands, new words), predicted from spelling.

DeepPhonemizer's US-English model, trained on CMUdict (MIT license; see `_deep_phonemizer.py`).
It is small (25 MB) and runs on the CPU in a few milliseconds per word.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from ...engine.models import Pronunciation
from ...engine.phonemes import split_ipa
from ..base import Availability, Download, G2PProvider, ProviderSettings

MODEL_FILES = ("config.json", "model.safetensors")
# The upload of the converted model (scripts/convert_deep_phonemizer.py) this code was tested with.
MODEL_REVISION = "2ff0a505d54b995a59ad65f4c1792b293a806412"


class DeepPhonemizerG2P(G2PProvider):
    name = "deep-phonemizer"

    class Settings(ProviderSettings):
        model: str = "dipumiah018/deep-phonemizer-en-us"  # Hugging Face repo, or a local folder
        revision: str | None = MODEL_REVISION  # None = the repo's latest
        device: str = "cpu"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._model = None

    def check_available(self) -> Availability:
        for module in ("torch", "safetensors"):
            if importlib.util.find_spec(module) is None:
                return Availability(False, f"python package {module!r} not installed (uv sync --extra models --extra cpu|cuda|rocm)")
        return Availability(True)

    def downloads(self) -> list[Download]:
        if Path(self.settings.model).expanduser().is_dir():
            return []
        return [Download("huggingface", self.settings.model, 0.03, MODEL_FILES, self.settings.revision)]

    def capabilities(self) -> dict[str, Any]:
        return {"accents": ["en-us"], "variants": False, "phoneme_set": "canonical-ipa", "any_word": True}

    def _load(self):
        if self._model is None:
            from ._deep_phonemizer import DeepPhonemizer

            folder = Path(self.settings.model).expanduser()
            if not folder.is_dir():
                from huggingface_hub import snapshot_download

                folder = Path(snapshot_download(self.settings.model, revision=self.settings.revision,
                                                allow_patterns=list(MODEL_FILES)))  # fmt: skip
            self._model = DeepPhonemizer(folder, self.settings.device)
        return self._model

    def pronounce(self, words: list[str]) -> dict[str, Pronunciation]:
        if not words:
            return {}
        predicted = self._load().predict(words)
        result = {}
        for word in words:
            phones = split_ipa(predicted.get(word, []))
            result[word] = Pronunciation(word, [phones] if phones else [], self.name if phones else "")
        return result

    def close(self) -> None:
        self._model = None

"""Phone recognition with wav2vec2 fine-tuned on espeak phones (CTC)."""

from __future__ import annotations

import importlib.util
from typing import Any

import numpy as np

from ...engine.phonemes import ENGLISH_PHONES, normalize_phone
from .._torch import quiet_transformers, resolve_device
from ..base import Availability, PhonemeRecognizer, ProviderSettings


class Wav2Vec2PhonemeRecognizer(PhonemeRecognizer):
    name = "wav2vec2"

    class Settings(ProviderSettings):
        model: str = "facebook/wav2vec2-lv-60-espeak-cv-ft"
        device: str = "auto"
        # The model is multilingual: restrict it to English sounds so feedback can be described in
        # English terms. Turn off to see non-English sounds (e.g. tones) the speaker produced.
        english_only: bool = True

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._parts = None

    def check_available(self) -> Availability:
        for module in ("torch", "transformers"):
            if importlib.util.find_spec(module) is None:
                return Availability(False, f"python package {module!r} not installed (uv sync --extra models)")
        return Availability(True)

    def capabilities(self) -> dict[str, Any]:
        return {"phoneme_set": "canonical-ipa", "multilingual": True, "gpu": True}

    def _load(self):
        if self._parts is None:
            from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForCTC, Wav2Vec2PhonemeCTCTokenizer

            import torch

            quiet_transformers()
            device = resolve_device(self.settings.device)
            # do_phonemize=False: we only decode, so the tokenizer needn't load espeak.
            tokenizer = Wav2Vec2PhonemeCTCTokenizer.from_pretrained(self.settings.model, do_phonemize=False)
            extractor = Wav2Vec2FeatureExtractor.from_pretrained(self.settings.model)
            model = Wav2Vec2ForCTC.from_pretrained(self.settings.model).to(device).eval()
            allowed = None
            if self.settings.english_only:
                allowed = torch.zeros(len(tokenizer), dtype=torch.bool)
                for token, idx in tokenizer.get_vocab().items():
                    if idx == tokenizer.pad_token_id or normalize_phone(token) in ENGLISH_PHONES:
                        allowed[idx] = True  # pad is the CTC blank and must stay
                allowed = allowed.to(device)
            self._parts = (tokenizer, extractor, model, device, allowed)
        return self._parts

    def recognize(self, samples: np.ndarray, sample_rate: int) -> list[str]:
        return [p for p, _ in self.recognize_timed(samples, sample_rate)]

    def recognize_timed(self, samples: np.ndarray, sample_rate: int) -> list[tuple[str, float]]:
        import torch

        tokenizer, extractor, model, device, allowed = self._load()
        inputs = extractor(samples, sampling_rate=sample_rate, return_tensors="pt")
        with torch.inference_mode():
            logits = model(inputs.input_values.to(device)).logits
            if allowed is not None:
                logits[..., : len(allowed)][..., ~allowed] = float("-inf")
        ids = torch.argmax(logits, dim=-1)[0].cpu().tolist()
        return ctc_phones(ids, tokenizer.convert_ids_to_tokens(ids), tokenizer.pad_token_id,
                          len(samples) / sample_rate)  # fmt: skip

    def close(self) -> None:
        self._parts = None


def ctc_phones(ids: list[int], tokens: list[str], blank_id: int, duration: float) -> list[tuple[str, float]]:
    """Greedy CTC decode keeping time: collapse repeats, drop blanks; time = frame centre in seconds."""
    if not ids:
        return []
    frame = duration / len(ids)
    out, prev = [], None
    for i, (token_id, token) in enumerate(zip(ids, tokens, strict=True)):
        if token_id != prev and token_id != blank_id:
            phone = normalize_phone(token)
            if phone and phone != "|" and not (phone.startswith("<") and phone.endswith(">")):
                out.append((phone, round((i + 0.5) * frame, 3)))
        prev = token_id
    return out

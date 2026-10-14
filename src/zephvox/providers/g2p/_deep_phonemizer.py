"""Inference for DeepPhonemizer's forward transformer: spelling in, phonemes out.

Adapted from DeepPhonemizer (https://github.com/as-ideas/DeepPhonemizer), MIT license (below).
Only inference is kept, and the model is read from config.json + model.safetensors (a conversion
of the en_us_cmudict_ipa_forward checkpoint) instead of a pickle.
"""

# MIT License
#
# Copyright (c) 2021 Axel Springer News Media & Tech GmbH & Co. KG - Ideas Engineering
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import annotations

import json
import math
from pathlib import Path

import torch
from torch import nn

PAD = "_"
END = "<end>"


class Tokenizer:
    """Symbols ↔ indices: 0 = pad (also the CTC blank), then one start token per language, then end."""

    def __init__(self, symbols: list[str], languages: list[str], char_repeats: int = 1, lowercase: bool = False):
        self.char_repeats = char_repeats
        self.lowercase = lowercase
        tokens = [PAD] + [f"<{lang}>" for lang in languages] + [END] + list(symbols)
        self.index = {t: i for i, t in enumerate(tokens)}
        self.symbols = dict(enumerate(tokens))
        self.end = self.index[END]
        self.special = {self.index[PAD], self.end} | {self.index[f"<{lang}>"] for lang in languages}

    def encode(self, text: str, lang: str) -> list[int]:
        chars = [c for c in text for _ in range(self.char_repeats)]
        if self.lowercase:
            chars = [c.lower() for c in chars]
        return [self.index[f"<{lang}>"]] + [self.index[c] for c in chars if c in self.index] + [self.end]

    def decode(self, indices: list[int]) -> list[str]:
        out = []
        for i in indices:
            if i == self.end:
                break
            if i not in self.special:
                out.append(self.symbols[i])
        return out


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 5000):
        super().__init__()
        self.scale = nn.Parameter(torch.ones(1))
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe = torch.zeros(max_len, d_model)
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer("pe", pe.unsqueeze(1), persistent=False)  # [T, 1, D]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.scale * self.pe[: x.size(0)]


class ForwardTransformer(nn.Module):
    def __init__(self, encoder_vocab: int, decoder_vocab: int, d_model: int, d_fft: int, layers: int, heads: int):
        super().__init__()
        self.embedding = nn.Embedding(encoder_vocab, d_model)
        self.pos_encoder = PositionalEncoding(d_model)
        layer = nn.TransformerEncoderLayer(d_model, heads, dim_feedforward=d_fft, dropout=0.0, activation="relu")
        self.encoder = nn.TransformerEncoder(layer, layers, norm=nn.LayerNorm(d_model), enable_nested_tensor=False)
        self.fc_out = nn.Linear(d_model, decoder_vocab)

    def forward(self, text: torch.Tensor) -> torch.Tensor:  # [N, T] → [N, T, V]
        x = text.transpose(0, 1)
        pad_mask = (x == 0).transpose(0, 1)
        x = self.encoder(self.pos_encoder(self.embedding(x)), src_key_padding_mask=pad_mask)
        return self.fc_out(x).transpose(0, 1)


class DeepPhonemizer:
    def __init__(self, model_dir: Path, device: str = "cpu"):
        from safetensors.torch import load_file

        config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        pre, dims = config["preprocessing"], config["model"]
        self.languages = pre["languages"]
        self.text = Tokenizer(pre["text_symbols"], self.languages, pre["char_repeats"], pre["lowercase"])
        self.phonemes = Tokenizer(pre["phoneme_symbols"], self.languages)
        self.device = torch.device(device)
        self.model = ForwardTransformer(len(self.text.index), len(self.phonemes.index), dims["d_model"],
                                        dims["d_fft"], dims["layers"], dims["heads"])  # fmt: skip
        state = {k: v.float() for k, v in load_file(model_dir / "model.safetensors").items()}
        self.model.load_state_dict(state)
        self.model.to(self.device).eval()

    @torch.no_grad()
    def predict(self, words: list[str], lang: str = "en_us", batch_size: int = 32) -> dict[str, list[str]]:
        """word → phoneme symbols (empty when the word has no letters the model knows)."""
        result: dict[str, list[str]] = {}
        todo = sorted({w for w in words if len(self.text.encode(w, lang)) > 2}, key=len)
        for start in range(0, len(todo), batch_size):
            batch = todo[start : start + batch_size]
            inputs = [torch.tensor(self.text.encode(w, lang)) for w in batch]
            padded = nn.utils.rnn.pad_sequence(inputs, batch_first=True).to(self.device)
            best = self.model(padded).argmax(-1).cpu()
            for word, row in zip(batch, best, strict=True):
                # CTC: drop blanks (0), then collapse repeats
                kept = row[row != 0]
                result[word] = self.phonemes.decode(torch.unique_consecutive(kept).tolist())
        return {w: result.get(w, []) for w in words}

"""Convert DeepPhonemizer's pickled checkpoint to the config.json + model.safetensors the
`deep-phonemizer` G2P driver reads. How the published model was made:

    uv run --with deep-phonemizer python scripts/convert_deep_phonemizer.py en_us_cmudict_ipa_forward.pt out/

The checkpoint is DeepPhonemizer's en_us_cmudict_ipa_forward (MIT license,
https://github.com/as-ideas/DeepPhonemizer). Loading it unpickles code, so only run this on a copy
you trust. The weights are stored as float16 (identical predictions); the fixed sin/cos position
table and the embedded word list are left out.
"""

import json
import sys
from pathlib import Path

import torch
from safetensors.torch import save_file


def main(src: str, out: str) -> None:
    checkpoint = torch.load(src, map_location="cpu", weights_only=False)
    cfg = checkpoint["config"]
    if cfg["model"]["type"] != "transformer":
        sys.exit("only the forward (CTC) model is supported")
    pre = cfg["preprocessing"]
    config = {
        "architecture": "deep-phonemizer-forward-transformer",
        "source": f"https://github.com/as-ideas/DeepPhonemizer (en_us_cmudict_ipa_forward, step {checkpoint['step']})",
        "model": {k: cfg["model"][k] for k in ("d_model", "d_fft", "layers", "heads")},
        "preprocessing": {
            "languages": pre["languages"],
            "text_symbols": list(pre["text_symbols"]),
            "phoneme_symbols": pre["phoneme_symbols"],
            "char_repeats": pre["char_repeats"],
            "lowercase": pre["lowercase"],
        },
    }
    state = {k: v.to(torch.float16).contiguous() for k, v in checkpoint["model"].items() if k != "pos_encoder.pe"}
    Path(out).mkdir(parents=True, exist_ok=True)
    save_file(state, f"{out}/model.safetensors", metadata={"format": "pt"})
    Path(out, "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:3])

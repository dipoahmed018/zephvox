# Third-party licenses

zephvox's own code is AGPL-3.0 (or a commercial license, see [LICENSING.md](LICENSING.md)). It
uses the packages and models below, which are downloaded during installation and keep their own
licenses. **The default installation contains no GPL code**; LGPL packages are used unmodified as
separate libraries.

## Included in this repository

| What | Where | License |
|---|---|---|
| CMU Pronouncing Dictionary | `src/zephvox/data/cmudict/` | BSD-style, Carnegie Mellon University (`LICENSE` next to it) |
| DeepPhonemizer inference code (adapted) | `src/zephvox/providers/g2p/_deep_phonemizer.py` | MIT, Axel Springer News Media & Tech (notice in the file) |
| zephvox-espeak plugin | `plugins/zephvox-espeak/` | GPL-3.0-or-later: a separate, optional package, **not** covered by the commercial license |

## Models (downloaded on first use)

| Model | Used for | License |
|---|---|---|
| openai/whisper-large-v3-turbo (and other Whisper sizes) | speech to text | MIT |
| Systran/faster-whisper-* | speech to text on CPU | MIT |
| facebook/wav2vec2-lv-60-espeak-cv-ft | recognizing the sounds you said | Apache-2.0 |
| dipumiah018/deep-phonemizer-en-us (DeepPhonemizer en_us_cmudict_ipa_forward, converted to safetensors) | pronouncing words no dictionary has | MIT |
| hexgrad/Kokoro-82M | practice voice | Apache-2.0 |
| Qwen3 (through Ollama) | grammar | Apache-2.0 |

Other models you configure yourself keep their own licenses.

## Python packages

| Package | Extra | License |
|---|---|---|
| numpy, httpx, platformdirs, pydantic | core | BSD / MIT |
| torch (CPU, CUDA or ROCm build) | cpu / cuda / rocm | BSD-style (bundles NVIDIA or AMD runtime libraries under their own terms) |
| transformers | models | Apache-2.0 |
| faster-whisper | models | MIT |
| av (PyAV; its wheels bundle FFmpeg's libraries) | models | BSD-3-Clause; FFmpeg: LGPL |
| safetensors | models | Apache-2.0 |
| misaki (US/UK dictionaries; installed without its GPL `en` extra) | models | Apache-2.0 |
| kokoro | voice | Apache-2.0 |
| num2words | voice | LGPL |
| attrs | voice | MIT |
| spacy, en-core-web-sm | voice | MIT |
| sounddevice, dbus-fast | desktop | MIT |
| pynput, python-xlib (Linux) | desktop | LGPL-3.0 / LGPL-2.1+ |
| fastapi, uvicorn, python-multipart | web | MIT / BSD-3-Clause / Apache-2.0 |

## System programs (optional)

| Program | Used for | License |
|---|---|---|
| Ollama | runs the grammar model | MIT |
| espeak-ng | robotic practice voice, if installed (run as a separate program) | GPL-3.0-or-later |
| ffmpeg | reading audio files, if PyAV is not installed | LGPL / GPL, depending on the build |

## Optional GPL plugin

`uv sync --extra espeak` installs [`plugins/zephvox-espeak`](plugins/zephvox-espeak), which
brings **phonemizer** and **espeakng-loader** (bundling **espeak-ng**), all GPL-3.0-or-later.
zephvox never imports them unless you install the plugin and choose its `espeak` driver.

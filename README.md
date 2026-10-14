# speakcheck

Record yourself speaking English, then get a list of your **pronunciation** and **grammar** mistakes,
each with the sentence it came from, what you said and what it should have been.

Everything runs offline, and every part is a plugin you can swap.

```
$ speakcheck record
Speak now. Press Enter to stop…

Pronunciation (1)
  1. think: you said /s ɪ ŋ k/, expected /θ ɪ ŋ k/  (θ→s)
     You said 's' as in see instead of 'th' as in think.
     “I think we should go now.” [0:00.2]

Grammar (1)
  1. "he go" → "he went"  (verb-tense)
     Use the past tense with "yesterday".
     “Yesterday he go to the market.” [0:01.8]
```

## Setup (Arch Linux, AMD GPU)

```sh
sudo pacman -S espeak-ng rocm-hip-runtime rocminfo ollama-rocm
sudo usermod -aG render,video $USER      # then log out and back in
rocminfo | grep gfx                      # should list your GPU (RX 6800 XT = gfx1030)
ollama serve & ollama pull qwen3:8b; kill %1   # one-time download into ~/.ollama

uv sync --extra models --extra desktop --extra web   # models, shortcuts + capture, web GUI
uv run speakcheck doctor                 # what this machine can run
```

If PyTorch does not see the GPU, try `export HSA_OVERRIDE_GFX_VERSION=10.3.0`.
The first analysis downloads Whisper large-v3-turbo (~1.6 GB) and wav2vec2 (~1.2 GB).

## The web GUI

```sh
uv run speakcheck serve --open           # http://127.0.0.1:8765
```

`serve` starts a local daemon: it keeps the models loaded, owns the microphone, registers global
shortcuts and serves the page. The **browser never records**. It shows live feedback and lets you
practise, and the engine does the recording.

- **Record**: press **Ctrl+Alt+R** anywhere (or the big button), speak, press again. The page shows a
  live level meter, then the analysis progress, then opens the report.
- **Report**: your transcript with mistakes highlighted (teal = pronunciation, amber = grammar). Click
  one to hear your own word, hear it said correctly, practise it, or mark it "not a mistake".
- **Practice**: hear the word, press **Ctrl+Alt+P** (or click) and say it. Recording stops by itself
  when you stop talking. You get a 0–100 score, every sound colored right or wrong, and a mouth tip.
  Repeat until it passes.
- **History / Progress / Settings**: past sessions, your weakest words and sounds, microphone choice,
  driver status.

Shortcuts are a plugin kind too (`[providers] triggers`):

| Driver | Where | Notes |
|---|---|---|
| `portal` | Linux (KDE Plasma, GNOME 48+, Hyprland; Wayland or X11) | The desktop asks once; rebind in system settings |
| `pynput` | Windows, macOS, Linux X11 | macOS asks for Accessibility permission |
| any OS | — | Bind `speakcheck toggle` / `speakcheck practice` in your OS shortcut settings. Both talk to the running daemon. |

Change the suggested keys in `config.toml`:

```toml
[shortcuts]
toggle_recording = "Ctrl+Alt+R"
practice_attempt = "Ctrl+Alt+P"
cancel = "Ctrl+Alt+X"
```

Frontend development: `cd web && npm install && npm run dev` (Vite proxies `/api` to the daemon).
`npm run build` writes the production page into `src/speakcheck/web/static/`.

## Command line

| Command | What it does |
|---|---|
| `speakcheck record` | record until you press Enter, then analyze |
| `speakcheck start` / `speakcheck stop` | record in the background (e.g. bind these to hotkeys) |
| `speakcheck analyze talk.mp3` | analyze any audio file |
| `speakcheck report [SESSION]` | show a saved report again (`--format markdown\|json`, `-o file`) |
| `speakcheck history` | your most frequent mistakes across sessions |
| `speakcheck providers` | which drivers are available, and which is selected |
| `speakcheck serve` | daemon + web GUI + global shortcuts |
| `speakcheck toggle` / `speakcheck practice` | start/stop a recording or practice attempt (uses the daemon when it runs) |

When the daemon is running, `record`, `start`, `stop`, `toggle` and `practice` are forwarded to it.

Useful flags: `--analyzers grammar` (only one ability), `--set stt=faster-whisper` (pick a driver),
`--config path.toml`. Sessions (audio + `result.json`) live in `~/.local/share/speakcheck/sessions/`.

## Architecture

```
CLI ──► Engine ──► Planner ──► Providers (drivers) ──► Artifacts ──► Analyzers ──► Findings ──► Reporters
```

- **Engine** (`src/speakcheck/engine/`): sessions, plugin registry, config, capability detection,
  artifact planner, events. It knows nothing about pronunciation or grammar.
- **Providers** (`src/speakcheck/providers/`): replaceable drivers, one contract per kind
  (`providers/base.py`).
- **Artifacts** (`engine/artifacts.py`): intermediate data computed once, only if an enabled analyzer
  needs it. Running grammar alone never loads the phoneme model.
- **Analyzers** (`src/speakcheck/analyzers/`): abilities. Each declares the artifacts and providers it
  needs and returns `Finding`s in one shared format.
- **Reporters** (`src/speakcheck/reporters/`): render findings as terminal text, Markdown or JSON.

| Kind | Built-in drivers (default first) |
|---|---|
| `capture` | `pipewire` (Linux), `sounddevice` (Windows/macOS/Linux) |
| `stt` | `hf-whisper` (transformers, GPU), `faster-whisper` (CPU) |
| `g2p` | `chain` (= `cmudict` then `espeak`), `cmudict`, `espeak` |
| `phonemes` | `wav2vec2` (`facebook/wav2vec2-lv-60-espeak-cv-ft`) |
| `llm` | `openai-compat` (Ollama `qwen3:8b` by default; also llama.cpp, vLLM, LM Studio, cloud APIs) |
| `tts` | `espeak-ng` (reference pronunciations in practice) |
| `triggers` | `portal`, `pynput` (global shortcuts) |

All G2P and phoneme drivers convert into one canonical IPA phone set (`engine/phonemes.py`).
That shared set is what makes mixing drivers safe.

### Configuration

`~/.config/speakcheck/config.toml`. Each stage takes a preference list, and the first available
driver wins:

```toml
[engine]
analyzers = ["pronunciation", "grammar"]

[providers]
stt = ["hf-whisper", "faster-whisper"]
g2p = ["chain"]

[provider.hf-whisper]
model = "openai/whisper-large-v3-turbo"

[provider.chain]
order = ["cmudict", "espeak"]      # for UK English: ["espeak"] plus [provider.espeak] language = "en-gb"

[provider.openai-compat]
model = "qwen3:8b"                 # or qwen3:14b — fits in 16 GB VRAM
autostart = true                   # run `ollama serve` only during analysis (default)

[analyzer.pronunciation]
threshold = 0.3                    # higher = stricter about what counts as a mistake
```

### Writing a plugin

Subclass the contract for its kind and register an entry point in your own package:

```toml
[project.entry-points."speakcheck.stt"]
parakeet = "speakcheck_parakeet:ParakeetSTT"
```

```python
from speakcheck.providers.base import STTProvider, Availability

class ParakeetSTT(STTProvider):
    name = "parakeet"
    def check_available(self): ...          # cheap; say *why* if it can't run
    def transcribe(self, samples, sample_rate): ...   # -> Transcript with word timestamps
```

Driver lifecycle, called by the engine:

| Method | When | Typical use |
|---|---|---|
| `check_available()` | choosing a driver | cheap check; never loads models |
| `prepare()` | once, right before first use | server-based drivers start their server (e.g. Ollama `autostart`); raise to fall back to the next driver |
| first call (`transcribe`, …) | during analysis | in-process drivers load models lazily |
| `close()` | after the analysis | free GPU memory; stop only processes `prepare()` started |

A new ability works the same way: subclass `analyzers.base.Analyzer`, set `needs` and `uses`, return
`Finding`s, and register it under `speakcheck.analyzers`. Reports, history and session storage
pick it up automatically.

## Tests

```sh
uv run pytest --cov                       # fast unit suite, no models needed
cd web && npm test                        # frontend unit tests
uv run python scripts/make_fixtures.py    # synthesize test audio with deliberate mistakes
uv run pytest -m "audio and models"       # real Whisper + G2P + wav2vec2
uv run pytest -m gpu                      # GPU visible to PyTorch
uv run pytest -m llm                      # live Ollama
```

## Limitations

- Speech-to-text tries to guess what you *meant*. A badly mispronounced word may come out as a
  different word, and then the mistake is missed. Whisper also sometimes "fixes" grammar while
  transcribing.
- Pronunciation is judged against standard US (or UK) English. Some findings are accent rather than
  mistakes.
- Thresholds are a first guess and need tuning on real speech.

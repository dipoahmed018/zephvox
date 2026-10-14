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

## Install

One line installs everything into a single folder: `~/speakcheck`, or `%LOCALAPPDATA%\speakcheck` on Windows.

```sh
# macOS / Linux
curl -LsSf https://raw.githubusercontent.com/dipoahmed018/speakcheck/main/install.sh | sh
```
```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/dipoahmed018/speakcheck/main/install.ps1 | iex"
```

The script installs [uv](https://docs.astral.sh/uv/) if needed, downloads speakcheck and starts `speakcheck setup`,
which:

1. **detects your hardware**: CPU, RAM, GPU and its memory, free disk space;
2. **recommends a profile** (below). Accept it or pick another;
3. **shows what it will download** and checks the disk space;
4. **installs [Ollama](https://ollama.com)** for grammar, if you agree (winget, Homebrew, pacman or Ollama's script);
5. **installs the matching PyTorch build** (NVIDIA → CUDA, AMD on Linux → ROCm, otherwise CPU; Macs use the Apple GPU);
6. **downloads the models** with progress bars;
7. **adds speakcheck to your app menu** and a `speakcheck` command to your terminal;
8. **runs a test analysis** to check it all works.

Nothing else needs a system install: espeak-ng and ffmpeg's decoders come with the Python packages.

### Profiles

| Profile | Recommended for | Speech to text | Grammar model |
|---|---|---|---|
| `large` | GPU with 16 GB+, or a Mac with 32 GB+ | Whisper large-v3-turbo (GPU) | qwen3:14b |
| `standard` | GPU with 10–16 GB, or a Mac with 16 GB+ | Whisper large-v3-turbo (GPU) | qwen3:8b |
| `small` | GPU with 6–10 GB, or a Mac with 8 GB | Whisper large-v3-turbo (GPU) | qwen3:4b |
| `cpu` | no usable GPU, 16 GB+ RAM | Whisper small.en (faster-whisper) | qwen3:4b (slow) |
| `cpu-light` | under 16 GB RAM | Whisper base.en (faster-whisper) | off (a cloud LLM can be added) |

Change profile any time in the page's **Settings**, or with `speakcheck setup` (which also installs
anything the new profile needs). A profile is only a starting point: anything you set in `config.toml`
wins over it. These thresholds are first estimates; tell us if a profile doesn't suit your machine.

### Afterwards

| Command | What it does |
|---|---|
| `speakcheck serve --open` | start speakcheck (or use the app-menu entry) |
| `speakcheck setup` | review the profile, repair the install; `--dry-run` only shows the plan |
| `speakcheck update` | install the latest release, keeping your settings |
| `speakcheck uninstall` | remove it (asks before deleting models or your recordings) |

Unattended install: `curl … | sh -s -- --profile cpu --yes` (Windows: set `SPEAKCHECK_SETUP_ARGS="--profile cpu --yes"`).
`SPEAKCHECK_DIR` changes the folder.

**GPU notes.**
- NVIDIA: the normal driver, 525 or newer. No CUDA toolkit is needed.
- AMD on Linux: PyTorch's ROCm build brings its own ROCm libraries. Your user must be in the `render` and
  `video` groups (setup tells you if not). If PyTorch can't use the card, setup offers the usual
  `HSA_OVERRIDE_GFX_VERSION` fix.
- AMD and Intel GPUs on Windows aren't supported by PyTorch, so those machines use a CPU profile.

### From a git checkout (development)

```sh
git clone https://github.com/dipoahmed018/speakcheck && cd speakcheck
uv run speakcheck setup      # same wizard; keeps the dev tools, and `update` is `git pull`
```

Or by hand: `uv sync --extra models --extra cuda --extra desktop --extra web --extra voice`, with
`cuda`, `rocm` or `cpu` for your hardware.

## The web GUI

```sh
speakcheck serve --open                  # http://127.0.0.1:8765  (in a git checkout: uv run speakcheck …)
```

`serve` starts a local daemon: it keeps the models loaded, owns the microphone, registers global
shortcuts and serves the page. The **browser never records**. It shows live feedback and lets you
practise, and the engine does the recording.

- **Record**: press **Ctrl+Shift+Alt+R** anywhere (or the big button), speak, press again. The page shows a
  live level meter, then the analysis progress, then opens the report.
- **Report**: your transcript with mistakes highlighted (teal = pronunciation, amber = grammar). Click
  one to hear your own word, hear it said correctly, practise it, or mark it "not a mistake".
- **Practice**: hear the word, press **Ctrl+Shift+Alt+P** (or click) and say it. Recording stops by itself
  when you stop talking. You get a 0–100 score, every sound colored right or wrong, and a mouth tip.
  Repeat until it passes.
- **History / Progress / Settings**: past sessions, your weakest words and sounds, microphone choice,
  driver status.

Shortcuts are a plugin kind too (`[providers] triggers`):

| Driver | Where | Notes |
|---|---|---|
| `portal` | Linux (KDE Plasma, GNOME 48+, Hyprland; Wayland or X11) | Run `speakcheck desktop-entry` once first, so the desktop files the shortcuts under "speakcheck" (not your terminal). The desktop asks once; rebind in system settings. |
| `pynput` | Windows, macOS, Linux X11 | macOS asks for Accessibility permission |
| any OS | — | Bind `speakcheck toggle` / `speakcheck practice` in your OS shortcut settings. Both talk to the running daemon. |

Change the suggested keys in `config.toml`:

```toml
[shortcuts]
toggle_recording = "Ctrl+Shift+Alt+R"
practice_attempt = "Ctrl+Shift+Alt+P"
cancel = "Ctrl+Shift+Alt+X"
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
| `speakcheck desktop-entry` | add speakcheck to the app menu (Linux: also gives its shortcuts a proper name) |
| `speakcheck toggle` / `speakcheck practice` | start/stop a recording or practice attempt (uses the daemon when it runs) |

When the daemon is running, `record`, `start`, `stop`, `toggle` and `practice` are forwarded to it.

Useful flags: `--analyzers grammar` (only one ability), `--set stt=faster-whisper` (pick a driver),
`--config path.toml`. Sessions (audio + `result.json`) live in your OS's app-data folder (Linux: `~/.local/share/speakcheck/sessions/`).

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

Two files in the project root, both git-ignored. Copy them from their templates:

- **`config.toml`** (from `config.example.toml`, which lists every setting): drivers, models, thresholds,
  shortcuts.
- **`.env`** (from `.env.example`): API keys and machine-specific environment variables (GPU overrides,
  model cache location). Variables already set in your shell win.

Both are found from where the code lives, so they apply however speakcheck starts: from a terminal
in any folder, from the app menu, or from a global shortcut. `--config` or `SPEAKCHECK_CONFIG` picks
another file. If you install speakcheck as a package without the project folder, it uses your OS's
config folder instead: `~/.config/speakcheck/`, `~/Library/Application Support/speakcheck/` or
`%LOCALAPPDATA%\speakcheck\`. `speakcheck doctor` shows which files are in use.

Each stage takes a preference list, and the first available driver wins:

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

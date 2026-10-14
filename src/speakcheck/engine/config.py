"""Configuration: which plugin to use for each stage, in order of preference, plus their settings.

Example `~/.config/speakcheck/config.toml`:

    [engine]
    analyzers = ["pronunciation", "grammar"]

    [providers]
    stt = ["hf-whisper", "faster-whisper"]   # first available wins

    [provider.hf-whisper]
    model = "openai/whisper-large-v3-turbo"

    [analyzer.pronunciation]
    threshold = 0.3
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import ConfigError

PROVIDER_KINDS = ("capture", "stt", "g2p", "phonemes", "llm", "tts", "triggers")

# Engine-level actions that trigger drivers (global shortcuts) can fire.
ACTIONS = ("toggle_recording", "practice_attempt", "cancel")
USER_SETTINGS_FILE = "settings.json"


def default_config_path() -> Path:
    if env := os.environ.get("SPEAKCHECK_CONFIG"):
        return Path(env)
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "speakcheck" / "config.toml"


def default_data_dir() -> Path:
    if env := os.environ.get("SPEAKCHECK_HOME"):
        return Path(env)
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "speakcheck"


class EngineSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analyzers: list[str] = ["pronunciation", "grammar"]
    data_dir: Path = Field(default_factory=default_data_dir)
    sentence_split: bool = True
    # Analyzer used to score practice attempts against a known text.
    practice_analyzer: str = "practice"
    # Practice attempts stop by themselves after this much silence (0 = only manual stop).
    practice_auto_stop_s: float = 1.2
    practice_max_s: float = 10.0


def _default_providers() -> dict[str, list[str]]:
    linux = sys.platform.startswith("linux")
    return {
        "capture": ["pipewire", "sounddevice"] if linux else ["sounddevice"],
        "stt": ["hf-whisper", "faster-whisper"],
        "g2p": ["chain"],
        "phonemes": ["wav2vec2"],
        "llm": ["openai-compat"],
        "tts": ["kokoro", "espeak-ng"],
        "triggers": ["portal", "pynput"] if linux else ["pynput"],
    }


def _default_shortcuts() -> dict[str, str]:
    # Three modifiers: practically never taken by apps or desktops on Linux, Windows or macOS, and
    # unlike Ctrl+Alt they don't collide with AltGr characters on international keyboard layouts.
    return {
        "toggle_recording": "Ctrl+Shift+Alt+R",
        "practice_attempt": "Ctrl+Shift+Alt+P",
        "cancel": "Ctrl+Shift+Alt+X",
    }


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: EngineSettings = Field(default_factory=EngineSettings)
    providers: dict[str, list[str]] = Field(default_factory=_default_providers)
    provider: dict[str, dict[str, Any]] = Field(default_factory=dict)
    analyzer: dict[str, dict[str, Any]] = Field(default_factory=dict)
    shortcuts: dict[str, str] = Field(default_factory=_default_shortcuts)

    def provider_settings(self, name: str) -> dict[str, Any]:
        return dict(self.provider.get(name, {}))

    def analyzer_settings(self, name: str) -> dict[str, Any]:
        return dict(self.analyzer.get(name, {}))

    def with_overrides(self, overrides: list[str]) -> Config:
        """Apply `kind=name[,name...]` overrides, e.g. from `--set stt=faster-whisper`."""
        providers = {k: list(v) for k, v in self.providers.items()}
        for item in overrides:
            kind, sep, names = item.partition("=")
            kind = kind.strip()
            if not sep or not names.strip():
                raise ConfigError(f"Override must look like kind=name, got {item!r}")
            providers[kind] = [n.strip() for n in names.split(",") if n.strip()]
        return self.model_copy(update={"providers": providers})


def load_config(path: Path | None = None) -> Config:
    """Load config from `path` (or the default location). Missing default file → defaults."""
    explicit = path is not None
    path = Path(path) if explicit else default_config_path()
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"Invalid TOML in {path}: {e}") from e
    elif explicit:
        raise ConfigError(f"Config file not found: {path}")

    # Stage lists and shortcuts in the file replace the defaults per key, not wholesale.
    providers = _default_providers()
    providers.update(data.pop("providers", {}) or {})
    shortcuts = _default_shortcuts()
    shortcuts.update(data.pop("shortcuts", {}) or {})
    unknown = set(shortcuts) - set(ACTIONS)
    if unknown:
        raise ConfigError(f"Unknown shortcut action(s) in {path}: {', '.join(sorted(unknown))}")
    try:
        config = Config(providers=providers, shortcuts=shortcuts, **data)
    except ValidationError as e:
        raise ConfigError(f"Invalid config in {path}:\n{e}") from e
    config.engine.data_dir = config.engine.data_dir.expanduser()
    return apply_user_settings(config, load_user_settings(config.engine.data_dir))


# --- settings changed from the GUI ------------------------------------------------------
# Kept apart from the hand-written config.toml (and layered over it) so we never rewrite
# the user's file.


def load_user_settings(data_dir: Path) -> dict[str, Any]:
    path = Path(data_dir) / USER_SETTINGS_FILE
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise ConfigError(f"Invalid settings file {path}: {e}") from e
    return data if isinstance(data, dict) else {}


def save_user_settings(data_dir: Path, settings: dict[str, Any]) -> None:
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    (Path(data_dir) / USER_SETTINGS_FILE).write_text(json.dumps(settings, indent=2))


def apply_user_settings(config: Config, settings: dict[str, Any]) -> Config:
    """Supported keys: `capture: {provider, device}`, `tts: {provider, voice}`, `analyzers: [...]`."""
    update: dict[str, Any] = {}
    provider = {k: dict(v) for k, v in config.provider.items()}
    for key, field in (("capture", "device"), ("tts", "voice")):
        chosen = settings.get(key) or {}
        if chosen.get("provider"):
            settings_for = provider.setdefault(chosen["provider"], {})
            if chosen.get(field) is None:
                settings_for.pop(field, None)  # back to the driver's default
            else:
                settings_for[field] = chosen[field]
            update["provider"] = provider
    if settings.get("analyzers"):
        update["engine"] = config.engine.model_copy(update={"analyzers": list(settings["analyzers"])})
    return config.model_copy(update=update) if update else config

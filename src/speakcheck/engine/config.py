"""Configuration: which plugin to use for each stage, in order of preference, plus their settings.

The config file is `config.toml` in the project root (copy `config.example.toml`). Installed as a
plain package, without a project folder, it is `<user config dir>/speakcheck/config.toml` instead
(`~/.config` on Linux, `~/Library/Application Support` on macOS, `%LOCALAPPDATA%` on Windows).

Example:

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
import re
import sys
import tomllib
from pathlib import Path
from typing import Any, Literal

import platformdirs
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import profiles
from .errors import ConfigError

PROVIDER_KINDS = ("capture", "stt", "g2p", "phonemes", "llm", "tts", "triggers")

# Engine-level actions that trigger drivers (global shortcuts) can fire.
ACTIONS = ("toggle_recording", "practice_attempt", "cancel")
USER_SETTINGS_FILE = "settings.json"


def project_root(package_dir: Path = Path(__file__).resolve().parents[1]) -> Path | None:
    """The source checkout this package runs from (`uv sync` installs it editable), else None.

    Found from the code's location, not the working directory: the daemon is often started from
    the app menu or a global shortcut, with the home folder as working directory.
    """
    root = package_dir.parent.parent  # <root>/src/speakcheck
    pyproject = root / "pyproject.toml"
    try:
        return root if 'name = "speakcheck"' in pyproject.read_text() else None
    except OSError:
        return None


def user_config_dir() -> Path:
    return Path(platformdirs.user_config_dir("speakcheck", appauthor=False))


def config_dirs() -> list[Path]:
    """Where `config.toml` and `.env` are looked up, first match first."""
    root = project_root()
    return [root, user_config_dir()] if root else [user_config_dir()]


def default_config_path() -> Path:
    if env := os.environ.get("SPEAKCHECK_CONFIG"):
        return Path(env)
    candidates = [d / "config.toml" for d in config_dirs()]
    return next((p for p in candidates if p.exists()), candidates[0])


def default_data_dir() -> Path:
    if env := os.environ.get("SPEAKCHECK_HOME"):
        return Path(env)
    # Linux: $XDG_DATA_HOME/speakcheck (~/.local/share/speakcheck)
    return Path(platformdirs.user_data_dir("speakcheck", appauthor=False))


# --- .env -------------------------------------------------------------------------------
# Machine-specific environment (API keys, GPU workarounds, model cache location). A daemon
# started from the app menu or a shortcut does not inherit the shell's exports, so they live here.


def parse_env(text: str) -> dict[str, str]:
    """`KEY=value` lines; `#` comments, an `export ` prefix and surrounding quotes are allowed."""
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def load_env(dirs: list[Path] | None = None) -> list[Path]:
    """Load `.env` files into the environment. Never overrides a variable that is already set
    (so the shell wins, then the project's file, then the user's). Returns the files loaded."""
    loaded = []
    for d in config_dirs() if dirs is None else dirs:
        path = d / ".env"
        try:
            values = parse_env(path.read_text())
        except OSError:
            continue
        for key, value in values.items():
            os.environ.setdefault(key, value)
        loaded.append(path)
    return loaded


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


class ServerLimits(BaseModel):
    """Per-account limits; `speakcheck server limits set` overrides them for one account or all."""

    model_config = ConfigDict(extra="forbid")

    max_audio_minutes: float = 30.0  # per job
    max_jobs: int = 2  # queued or running at once
    storage_mb: int = 2048  # synced history
    requests_per_minute: int = 120


class ServerSettings(BaseModel):
    """`speakcheck server serve`: the engine as a service for many accounts."""

    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = 8770
    data_dir: Path | None = None  # default: <engine.data_dir>/server
    job_ttl_hours: float = 24.0  # finished jobs (audio and result) are deleted after this
    max_upload_mb: int = 200
    practice_workers: int = 2  # practice runs on its own threads, never behind long jobs
    # Webhooks to private or local addresses are refused unless allowed (a user could otherwise
    # make the server call services on its own network).
    webhook_allow_private: bool = False
    limits: ServerLimits = Field(default_factory=ServerLimits)


class RemoteSettings(BaseModel):
    """Use a speakcheck server for analysis (client mode), and/or sync history with it."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["local", "remote"] = "local"
    url: str | None = None
    # Extra headers for every request, e.g. for a proxy in front of the server. `${VAR}` in a
    # value is read from the environment (.env), so secrets needn't sit in config.toml.
    headers: dict[str, str] = Field(default_factory=dict)
    sync: bool | None = None  # back up history to the server; default: on in remote mode only
    device_name: str | None = None

    @property
    def syncing(self) -> bool:
        return bool(self.url) and (self.sync if self.sync is not None else self.mode == "remote")


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

    profile: str | None = None
    # The file this was loaded from (not a setting): where the GUI writes a profile change.
    source: Path | None = Field(default=None, exclude=True)
    engine: EngineSettings = Field(default_factory=EngineSettings)
    providers: dict[str, list[str]] = Field(default_factory=_default_providers)
    provider: dict[str, dict[str, Any]] = Field(default_factory=dict)
    analyzer: dict[str, dict[str, Any]] = Field(default_factory=dict)
    shortcuts: dict[str, str] = Field(default_factory=_default_shortcuts)
    server: ServerSettings = Field(default_factory=ServerSettings)
    remote: RemoteSettings = Field(default_factory=RemoteSettings)

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

    profile = data.pop("profile", None)
    if profile is not None:
        data = merge(profiles.get(profile, path).overlay, data)

    # Stage lists and shortcuts in the file replace the defaults per key, not wholesale.
    providers = _default_providers()
    providers.update(data.pop("providers", {}) or {})
    shortcuts = _default_shortcuts()
    shortcuts.update(data.pop("shortcuts", {}) or {})
    unknown = set(shortcuts) - set(ACTIONS)
    if unknown:
        raise ConfigError(f"Unknown shortcut action(s) in {path}: {', '.join(sorted(unknown))}")
    try:
        config = Config(profile=profile, source=path, providers=providers, shortcuts=shortcuts, **data)
    except ValidationError as e:
        raise ConfigError(f"Invalid config in {path}:\n{e}") from e
    config.engine.data_dir = config.engine.data_dir.expanduser()
    return apply_user_settings(config, load_user_settings(config.engine.data_dir))


def merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge tables; any other value (lists included) in `override` replaces the base one."""
    out = dict(base)
    for key, value in override.items():
        out[key] = merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


PROFILE_LINE = re.compile(r"^profile\s*=.*$", re.M)


def write_profile(path: Path, name: str, template: Path | None = None) -> None:
    """Set `profile = "name"` in config.toml, leaving every other line as the user wrote it.

    A missing file starts from `template` (config.example.toml), so its options stay documented.
    """
    profiles.get(name, path)  # validate
    line = f'profile = "{name}"'
    if path.exists():
        text = path.read_text()
    else:
        text = template.read_text() if template and template.exists() else ""
    head, sep, rest = text.partition("\n[")  # a top-level key must come before the first table
    if PROFILE_LINE.search(head):
        head = PROFILE_LINE.sub(line, head, count=1)
    else:
        head = f"{line}   # chosen by `speakcheck setup`: {', '.join([*profiles.PROFILES, profiles.CUSTOM])}\n\n{head}"
    path.write_text(head + sep + rest)


def choose_profile(path: Path, name: str, template: Path | None = None) -> None:
    """Switch to a profile (setup or the GUI). Picking one is explicit, so the profile's analyzer
    choice replaces one saved earlier from the GUI."""
    write_profile(path, name, template)
    analyzers = profiles.get(name, path).overlay.get("engine", {}).get("analyzers")
    if analyzers is not None:
        data_dir = load_config(path).engine.data_dir
        stored = load_user_settings(data_dir)
        if stored.pop("analyzers", None) is not None:
            save_user_settings(data_dir, stored)


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
    """Supported keys: `capture: {provider, device}`, `tts: {provider, voice}`, `analyzers: [...]`,
    `remote: {mode, url, headers, sync, device_name}`."""
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
    if isinstance(settings.get("remote"), dict):
        update["remote"] = RemoteSettings(**{**config.remote.model_dump(), **settings["remote"]})
    return config.model_copy(update=update) if update else config

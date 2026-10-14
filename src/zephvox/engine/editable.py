"""Every option the page can change: what it is, where its value comes from, and saving changes.

Changes from the page go into an overlay in settings.json (`"config"`), layered over config.toml, so
the hand-written file is never rewritten. Each option reports its value from the defaults, the
profile and config.toml (`base`) and the overlay on top, so the page can show where a value comes
from and put it back.
"""

from __future__ import annotations

import re
import tomllib
import types
import typing
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from .config import (
    PROVIDER_KINDS,
    Config,
    EngineSettings,
    ServerLimits,
    ServerSettings,
    load_user_settings,
    merge,
)
from .errors import ConfigError

Path_ = tuple[str, ...]

# Not editable from the page: where the page's own settings live, and what other cards handle.
READ_ONLY = {("engine", "data_dir"), ("engine", "practice_analyzer")}
ENGINE_FIELDS = ["analyzers", "sentence_split", "notifications", "practice_auto_stop_s", "practice_max_s"]


# --- the overlay --------------------------------------------------------------------------


def legacy_overlay(stored: dict[str, Any]) -> dict[str, Any]:
    """settings.json keys from before the overlay existed, as overlay entries."""
    overlay: dict[str, Any] = {}
    for key, field in (("capture", "device"), ("tts", "voice")):
        chosen = stored.get(key) or {}
        if chosen.get("provider") and chosen.get(field) is not None:
            overlay.setdefault("provider", {}).setdefault(chosen["provider"], {})[field] = chosen[field]
    if stored.get("analyzers"):
        overlay.setdefault("engine", {})["analyzers"] = list(stored["analyzers"])
    return overlay


def overlay_of(stored: dict[str, Any]) -> dict[str, Any]:
    return merge(legacy_overlay(stored), stored.get("config") or {})


def get_path(data: dict[str, Any], path: Path_) -> Any:
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def has_path(data: dict[str, Any], path: Path_) -> bool:
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return False
        data = data[key]
    return True


def set_path(data: dict[str, Any], path: Path_, value: Any) -> None:
    for key in path[:-1]:
        data = data.setdefault(key, {})
    data[path[-1]] = value


def unset_path(data: dict[str, Any], path: Path_) -> None:
    """Remove a value and any tables it leaves empty."""
    trail = []
    for key in path[:-1]:
        if not isinstance(data.get(key), dict):
            return
        trail.append((data, key))
        data = data[key]
    data.pop(path[-1], None)
    for parent, key in reversed(trail):
        if parent[key]:
            break
        del parent[key]


def apply_changes(stored: dict[str, Any], changes: list[dict[str, Any]]) -> dict[str, Any]:
    """settings.json with `changes` ([{path: [...], value: …, reset: bool}]) applied to its overlay.

    The older keys are folded into the overlay on the first change, so there is one place to look."""
    out = {k: v for k, v in stored.items() if k not in ("capture", "tts", "analyzers")}
    overlay = overlay_of(stored)
    for change in changes:
        path = tuple(str(p) for p in change.get("path") or ())
        if not path or path[0] not in ("engine", "providers", "provider", "analyzer", "shortcuts", "server"):
            raise ConfigError(f"Can't change {'.'.join(path) or 'nothing'} from the page")
        if path in READ_ONLY:
            raise ConfigError(f"{'.'.join(path)} can only be changed in config.toml")
        if change.get("reset"):
            unset_path(overlay, path)
        else:
            set_path(overlay, path, change.get("value"))
    if overlay:
        out["config"] = overlay
    else:
        out.pop("config", None)
    return out


# --- describing the options ---------------------------------------------------------------


def _field_type(annotation: Any) -> dict[str, Any]:
    """A pydantic annotation as a form control: bool, int, float, str, list, dict, or a choice."""
    origin = typing.get_origin(annotation)
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    if origin in (typing.Union, types.UnionType):
        inner = _field_type(args[0]) if len(args) == 1 else {"type": "str"}
        return {**inner, "nullable": True}
    if origin is Literal:
        return {"type": "choice", "choices": [str(a) for a in typing.get_args(annotation)]}
    if origin in (list, tuple):
        return {"type": "list"}
    if origin is dict:
        return {"type": "dict"}
    if annotation is bool:
        return {"type": "bool"}
    if annotation is int:
        return {"type": "int"}
    if annotation is float:
        return {"type": "float"}
    if annotation is Path:
        return {"type": "str"}
    return {"type": "str"}


def fields_of(model: type[BaseModel], skip: set[str] | frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    out = []
    for name, info in model.model_fields.items():
        if name in skip or isinstance(info.annotation, type) and issubclass(info.annotation, BaseModel):
            continue
        default = info.get_default(call_default_factory=True)
        out.append({"key": name, **_field_type(info.annotation), "default": _jsonable(default)})
    return out


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


DOC_LINE = re.compile(r"^#\s*([A-Za-z_][\w-]*)\s*=\s*(.*?)\s*(?:#\s*(.+))?$")


def docs_from_example(path: Path | None) -> dict[str, str]:
    """The comments in config.example.toml, by option ("provider.hf-whisper.device" → "auto = …")."""
    if path is None or not path.exists():
        return {}
    docs: dict[str, str] = {}
    section: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line.startswith("["):
            name, _, comment = line.partition("]")
            section = name.strip("[ ").split(".")
            if comment.strip().startswith("#"):
                docs[".".join(section)] = comment.strip()[1:].strip()
            continue
        m = DOC_LINE.match(line)
        if m and m.group(3) and section:
            docs[".".join([*section, m.group(1)])] = m.group(3).strip()
    return docs


def suggestions() -> dict[str, list[dict[str, str]]]:
    """Known good values for free-text options (any other value is still allowed)."""
    from ..install import ollama
    from ..install.custom import FASTER, GRAMMAR, WHISPER
    from ..providers.tts.kokoro import VOICES

    def opts(items):
        return [{"value": k, "label": f"{label}" + (f" ({note})" if note else "")} for k, label, note in items]

    installed = []
    try:
        installed = [m for m, *_ in GRAMMAR if ollama.has_model(m)]
    except Exception:  # no Ollama on this machine: still offer the list
        installed = []
    grammar = [{"value": m, "label": f"{m}" + (" (downloaded)" if m in installed else f" ({note})" if note else "")}
               for m, note, _ in GRAMMAR]  # fmt: skip
    devices = [{"value": v, "label": label} for v, label in
               (("auto", "auto: GPU if there is one"), ("cpu", "cpu"), ("cuda", "cuda (NVIDIA or AMD ROCm)"),
                ("mps", "mps (Apple GPU)"))]  # fmt: skip
    return {
        "provider.hf-whisper.model": opts(WHISPER),
        "provider.faster-whisper.model": opts(FASTER),
        "provider.openai-compat.model": grammar,
        "provider.kokoro.voice": [{"value": v, "label": label} for v, (label, _) in VOICES.items()],
        "provider.misaki.accent": [{"value": "en-us", "label": "American"}, {"value": "en-gb", "label": "British"}],
        "provider.espeak.language": [{"value": "en-us", "label": "American"}, {"value": "en-gb", "label": "British"}],
        "provider.hf-whisper.device": devices,
        "provider.wav2vec2.device": devices,
        "provider.kokoro.device": devices,
        "provider.deep-phonemizer.device": devices,
        "provider.faster-whisper.device": [{"value": "cpu", "label": "cpu"}, {"value": "cuda", "label": "cuda"}],
        "provider.faster-whisper.compute_type": [{"value": v, "label": v} for v in ("int8", "float16", "float32")],
    }


def describe(config: Config, base: Config, overlay: dict[str, Any], file_data: dict[str, Any],
             registry: Any, availability: dict[tuple[str, str], tuple[bool, str]],
             example: Path | None) -> dict[str, Any]:  # fmt: skip
    """Everything the Settings page needs to show and edit the configuration."""
    providers: dict[str, Any] = {}
    for kind in PROVIDER_KINDS:
        names = registry.names(kind)
        drivers = []
        for name in names:
            cls = registry.get(kind, name)
            ok, reason = availability.get((kind, name), (True, ""))
            drivers.append({
                "name": name, "available": ok, "reason": reason,
                "fields": fields_of(cls.Settings),
                "values": {**cls.Settings().model_dump(mode="json"), **config.provider_settings(name)},
                "base": {**cls.Settings().model_dump(mode="json"), **base.provider_settings(name)},
            })  # fmt: skip
        providers[kind] = {"order": config.providers.get(kind, []), "base_order": base.providers.get(kind, []),
                           "drivers": drivers}  # fmt: skip
    analyzers = {}
    for name in registry.names("analyzers"):
        cls = registry.get("analyzers", name)
        analyzers[name] = {
            "fields": fields_of(cls.Settings),
            "values": {**cls.Settings().model_dump(mode="json"), **config.analyzer_settings(name)},
            "base": {**cls.Settings().model_dump(mode="json"), **base.analyzer_settings(name)},
        }
    return {
        "profile": config.profile,
        "source": str(config.source) if config.source else None,
        "engine": {
            "fields": [f for f in fields_of(EngineSettings) if f["key"] in ENGINE_FIELDS],
            "values": config.engine.model_dump(mode="json"),
            "base": base.engine.model_dump(mode="json"),
            "data_dir": str(config.engine.data_dir),
        },
        "providers": providers,
        "analyzers": analyzers,
        "shortcuts": {"values": config.shortcuts, "base": base.shortcuts},
        "server": {
            "fields": fields_of(ServerSettings, skip={"limits"}),
            "values": config.server.model_dump(mode="json", exclude={"limits"}),
            "base": base.server.model_dump(mode="json", exclude={"limits"}),
            "limits": {"fields": fields_of(ServerLimits), "values": config.server.limits.model_dump(),
                       "base": base.server.limits.model_dump()},  # fmt: skip
        },
        "overlay": overlay,
        "in_file": _paths(file_data),
        "docs": docs_from_example(example),
        "suggestions": suggestions(),
    }


def _paths(data: dict[str, Any], prefix: Path_ = ()) -> list[str]:
    """Every option set in config.toml, as "provider.hf-whisper.model"."""
    out = []
    for key, value in data.items():
        if isinstance(value, dict):
            out.extend(_paths(value, (*prefix, key)))
        else:
            out.append(".".join((*prefix, key)))
    return out


def read_file(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError:
        return {}


def stored_settings(data_dir: Path) -> dict[str, Any]:
    return load_user_settings(data_dir)

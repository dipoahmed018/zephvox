"""Plugin discovery. Built-in and third-party plugins are found the same way: entry points.

A third-party package adds a driver with, e.g.:

    [project.entry-points."speakcheck.stt"]
    parakeet = "speakcheck_parakeet:ParakeetSTT"
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from importlib.metadata import EntryPoint, entry_points

from .errors import PluginNotFound

PLUGIN_KINDS = ("capture", "stt", "g2p", "phonemes", "llm", "tts", "triggers", "analyzers", "reporters")

EntryPointsFn = Callable[[str], Iterable[EntryPoint]]


def _default_entry_points(group: str) -> Iterable[EntryPoint]:
    return entry_points(group=group)


class Registry:
    def __init__(self, entry_points_fn: EntryPointsFn | None = _default_entry_points) -> None:
        self._entry_points_fn = entry_points_fn
        self._plugins: dict[str, dict[str, type]] = {kind: {} for kind in PLUGIN_KINDS}
        self.broken: dict[tuple[str, str], str] = {}
        self._loaded = entry_points_fn is None

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        for kind in PLUGIN_KINDS:
            for ep in self._entry_points_fn(f"speakcheck.{kind}"):
                # Explicitly registered plugins win over discovered ones.
                if ep.name in self._plugins[kind]:
                    continue
                try:
                    self._plugins[kind][ep.name] = ep.load()
                except Exception as e:  # one broken plugin must not take down the rest
                    self.broken[(kind, ep.name)] = f"{type(e).__name__}: {e}"

    def register(self, kind: str, name: str, cls: type) -> None:
        if kind not in self._plugins:
            raise ValueError(f"Unknown plugin kind {kind!r}")
        self._plugins[kind][name] = cls

    def get(self, kind: str, name: str) -> type:
        self._ensure_loaded()
        try:
            return self._plugins[kind][name]
        except KeyError:
            raise PluginNotFound(kind, name, self.names(kind)) from None

    def names(self, kind: str) -> list[str]:
        self._ensure_loaded()
        return sorted(self._plugins.get(kind, {}))

"""Global shortcuts with `pynput`: Windows, macOS and Linux on X11 (not Wayland)."""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Callable
from typing import Any

from ..base import Availability, TriggerProvider

_MODIFIERS = {"ctrl": "<ctrl>", "control": "<ctrl>", "alt": "<alt>", "shift": "<shift>", "super": "<cmd>",
              "meta": "<cmd>", "win": "<cmd>", "cmd": "<cmd>"}  # fmt: skip


def to_pynput_hotkey(combo: str) -> str:
    """"Ctrl+Alt+R" → "<ctrl>+<alt>+r"; named keys like F5/Space → "<f5>"/"<space>"."""
    parts = [p.strip() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"Empty shortcut {combo!r}")
    *mods, key = parts
    out = []
    for m in mods:
        if m.lower() not in _MODIFIERS:
            raise ValueError(f"Unknown modifier {m!r} in {combo!r}")
        out.append(_MODIFIERS[m.lower()])
    out.append(key.lower() if len(key) == 1 else f"<{key.lower()}>")
    return "+".join(out)


class PynputTriggers(TriggerProvider):
    name = "pynput"

    def __init__(self, *args: Any, keyboard: Any = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._keyboard = keyboard  # injectable for tests
        self._listener: Any = None

    def check_available(self) -> Availability:
        if self._keyboard is None and importlib.util.find_spec("pynput") is None:
            return Availability(False, "python package 'pynput' not installed (uv sync --extra desktop)")
        if sys.platform.startswith("linux"):
            if os.environ.get("XDG_SESSION_TYPE") == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
                return Availability(False, "Wayland blocks global key listening; use the 'portal' driver")
            if not os.environ.get("DISPLAY"):
                return Availability(False, "no X11 display")
        return Availability(True)

    def describe(self) -> str:
        if sys.platform == "darwin":
            return ("Change the keys in speakcheck's config ([shortcuts]). macOS asks once for "
                    "Accessibility permission for your terminal.")  # fmt: skip
        return "Change the keys in speakcheck's config file ([shortcuts] section)."

    def start(self, bindings: dict[str, str], fire: Callable[[str], None]) -> None:
        if self._keyboard is None:
            from pynput import keyboard

            self._keyboard = keyboard
        hotkeys = {to_pynput_hotkey(combo): (lambda a=action: fire(a)) for action, combo in bindings.items()}
        self._listener = self._keyboard.GlobalHotKeys(hotkeys)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def close(self) -> None:
        self.stop()

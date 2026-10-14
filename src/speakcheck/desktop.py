"""Linux desktop integration: an app-menu entry, which also gives the shortcut portal an app identity.

Without it, desktops attribute speakcheck's global shortcuts to whatever program launched it
(e.g. the terminal).
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

APP_ID = "io.github.speakcheck"

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="16" fill="#D9A05B"/>
<path d="M18 26v12M26 18v28M34 24v16M42 28v8M48 30v4" stroke="#1C1411" stroke-width="5" stroke-linecap="round"/>
</svg>
"""


def applications_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "applications"


def desktop_entry(python: str, icon: Path) -> str:
    exec_line = " ".join(shlex.quote(p) for p in (python, "-m", "speakcheck.cli", "serve", "--open"))
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=speakcheck",
        "GenericName=Spoken English coach",
        "Comment=Find and practise your pronunciation and grammar mistakes",
        f"Exec={exec_line}",
        f"Icon={icon}",
        "Terminal=false",
        "Categories=Education;Languages;",
        "Keywords=pronunciation;grammar;english;speech;practice;",
        "",
    ])  # fmt: skip


def install(python: str | None = None) -> Path:
    """Write the desktop entry (and its icon); returns the .desktop path."""
    apps = applications_dir()
    apps.mkdir(parents=True, exist_ok=True)
    icon = apps.parent / "icons" / f"{APP_ID}.svg"
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_text(ICON_SVG)
    path = apps / f"{APP_ID}.desktop"
    path.write_text(desktop_entry(python or sys.executable, icon))
    return path

"""App-menu launchers: a desktop entry on Linux, a Start-menu shortcut on Windows, an app on macOS.

On Linux the entry also gives the shortcut portal an app identity. Without it, desktops attribute
zephvox's global shortcuts to whatever program launched it (e.g. the terminal).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

APP_ID = "io.github.zephvox"
LEGACY_APP_ID = "io.github.speakcheck"  # the app's name before zephvox

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="16" fill="#D9A05B"/>
<path d="M18 26v12M26 18v28M34 24v16M42 28v8M48 30v4" stroke="#1C1411" stroke-width="5" stroke-linecap="round"/>
</svg>
"""


def applications_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "applications"


def desktop_entry(python: str, icon: Path) -> str:
    exec_line = " ".join(shlex.quote(p) for p in (python, "-m", "zephvox.cli", "serve", "--open"))
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=zephvox",
        "GenericName=Spoken English coach",
        "Comment=Find and practice your pronunciation and grammar mistakes",
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
    icon.write_text(ICON_SVG, encoding="utf-8")
    path = apps / f"{APP_ID}.desktop"
    path.write_text(desktop_entry(python or sys.executable, icon), encoding="utf-8")
    _remove_legacy()
    return path


def _remove_legacy() -> None:
    """The entry the app had under its old name, so the menu doesn't list it twice."""
    apps = applications_dir()
    (apps / f"{LEGACY_APP_ID}.desktop").unlink(missing_ok=True)
    (apps.parent / "icons" / f"{LEGACY_APP_ID}.svg").unlink(missing_ok=True)


def remove() -> list[Path]:
    apps = applications_dir()
    paths = [apps / f"{APP_ID}.desktop", apps.parent / "icons" / f"{APP_ID}.svg"]
    for path in paths:
        path.unlink(missing_ok=True)
    _remove_legacy()
    return paths


# --- Windows ----------------------------------------------------------------------------


def windows_shortcut_path() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / \
        "zephvox.lnk"


def ps_quote(value: object) -> str:
    """A PowerShell single-quoted string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def install_windows(python: str) -> Path:
    """A Start-menu shortcut. Its console window is the running app: closing it stops zephvox."""
    path = windows_shortcut_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    script = "; ".join([
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({ps_quote(path)})",
        f"$s.TargetPath = {ps_quote(python)}",
        "$s.Arguments = '-m zephvox.cli serve --open'",
        f"$s.WorkingDirectory = {ps_quote(Path(python).parent)}",
        "$s.Description = 'Find and practice your pronunciation and grammar mistakes'",
        "$s.Save()",
    ])  # fmt: skip
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, capture_output=True)
    return path


# --- macOS ------------------------------------------------------------------------------


def mac_app_path() -> Path:
    return Path.home() / "Applications" / "zephvox.app"


def mac_info_plist() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>zephvox</string>
  <key>CFBundleIdentifier</key><string>{APP_ID}</string>
  <key>CFBundleExecutable</key><string>zephvox</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>NSMicrophoneUsageDescription</key><string>zephvox records your voice to find pronunciation and grammar mistakes.</string>
</dict></plist>
"""


def install_mac(python: str) -> Path:
    app = mac_app_path()
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    (app / "Contents" / "Info.plist").write_text(mac_info_plist(), encoding="utf-8")
    launcher = macos / "zephvox"
    launcher.write_text(f"#!/bin/sh\nexec {shlex.quote(python)} -m zephvox.cli serve --open\n", encoding="utf-8")
    launcher.chmod(0o755)
    return app


# --- any OS -----------------------------------------------------------------------------


def install_launcher(python: str | None = None) -> Path:
    python = python or sys.executable
    if sys.platform == "win32":
        return install_windows(python)
    if sys.platform == "darwin":
        return install_mac(python)
    return install(python)


def remove_launcher() -> None:
    if sys.platform == "win32":
        windows_shortcut_path().unlink(missing_ok=True)
    elif sys.platform == "darwin":
        import shutil

        shutil.rmtree(mac_app_path(), ignore_errors=True)
    else:
        remove()


# --- `zephvox` on PATH ---------------------------------------------------------------
# uv's own installer puts ~/.local/bin on PATH; a link there makes `zephvox` work in any
# terminal without `uv run` (which would also re-sync the environment on every call).


def command_shim_path() -> Path:
    return Path.home() / ".local" / "bin" / ("zephvox.cmd" if os.name == "nt" else "zephvox")


def install_command(python: str | None = None) -> Path:
    scripts = Path(python or sys.executable).parent  # the environment's bin/ or Scripts/
    shim = command_shim_path()
    shim.parent.mkdir(parents=True, exist_ok=True)
    if shim.is_symlink() or shim.exists():
        shim.unlink()
    _remove_legacy_command()  # the command the app had before; it no longer works
    if os.name == "nt":
        shim.write_text(f'@"{scripts / "zephvox.exe"}" %*\r\n', encoding="utf-8")
    else:
        shim.symlink_to(scripts / "zephvox")
    return shim


def command_on_path() -> bool:
    return str(command_shim_path().parent) in os.environ.get("PATH", "").split(os.pathsep)


def _remove_legacy_command() -> None:
    """The `speakcheck` command from before the rename, if it is ours (not some other program)."""
    shim = command_shim_path().with_name("speakcheck.cmd" if os.name == "nt" else "speakcheck")
    try:
        ours = shim.is_symlink() and shim.resolve().name == "speakcheck"
        if os.name == "nt" and shim.exists():
            ours = "speakcheck.exe" in shim.read_text(encoding="utf-8")
        if ours:
            shim.unlink()
    except OSError:
        pass


def remove_command() -> None:
    shim = command_shim_path()
    if shim.is_symlink() or shim.exists():
        shim.unlink()
    _remove_legacy_command()

"""Desktop notifications, for actions started with a global shortcut (the page may not be visible).

Linux: `notify-send` (libnotify; KDE, GNOME and most desktops have it). macOS: `osascript`.
Windows: a PowerShell balloon tip. Anything missing or failing is silently skipped: a notification
is a courtesy, never a reason for an action to fail.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable

APP = "speakcheck"

Runner = Callable[..., object]


class Notifier:
    def __init__(self, enabled: bool = True, runner: Runner = subprocess.Popen, platform: str = sys.platform):
        self.enabled = enabled
        self.runner = runner
        self.platform = platform

    def __call__(self, title: str, body: str = "") -> None:
        if not self.enabled:
            return
        try:
            command = self.command(title, body)
            if command:
                self.runner(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    def command(self, title: str, body: str) -> list[str] | None:
        if self.platform.startswith("linux"):
            binary = shutil.which("notify-send")
            if binary is None:
                return None
            return [binary, "--app-name", APP, "--icon", "audio-input-microphone", "--expire-time", "6000",
                    "--hint", "string:x-canonical-private-synchronous:speakcheck", title, body]  # fmt: skip
        if self.platform == "darwin":
            script = f"display notification {_applescript(body)} with title {_applescript(title)}"
            return ["osascript", "-e", script]
        if self.platform == "win32":
            text = f"{title}: {body}" if body else title
            script = (
                "Add-Type -AssemblyName System.Windows.Forms; $n = New-Object System.Windows.Forms.NotifyIcon; "
                "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
                f"$n.ShowBalloonTip(6000, '{APP}', '{text.replace(chr(39), chr(39) * 2)}', 'Info'); "
                "Start-Sleep -Seconds 7; $n.Dispose()"
            )
            return ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script]
        return None


def _applescript(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

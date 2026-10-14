"""Run the server in the background, started with the computer: a systemd user unit on Linux,
a LaunchAgent on macOS, a scheduled task (at logon) on Windows. No administrator rights needed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

NAME = "zephvox-server"
MAC_LABEL = "com.zephvox.server"
# The names from before the rename: replaced when the service is installed, removed with it.
LEGACY_NAME = "speakcheck-server"
LEGACY_MAC_LABEL = "com.speakcheck.server"

Runner = Callable[..., subprocess.CompletedProcess]


def command(python: str, config: Path | None, host: str | None, port: int | None) -> list[str]:
    cmd = [python, "-m", "zephvox.cli", "server", "serve"]
    if config:
        cmd += ["--config", str(config)]
    if host:
        cmd += ["--host", host]
    if port:
        cmd += ["--port", str(port)]
    return cmd


def systemd_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".config" / "systemd" / "user" / f"{NAME}.service"


def systemd_unit(cmd: list[str], workdir: Path) -> str:
    quoted = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    return f"""[Unit]
Description=zephvox server
After=network-online.target

[Service]
WorkingDirectory={workdir}
ExecStart={quoted}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def launchd_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"


def launchd_plist(cmd: list[str], workdir: Path, log: Path) -> str:
    from xml.sax.saxutils import escape

    args = "\n".join(f"    <string>{escape(c)}</string>" for c in cmd)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{MAC_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
{args}
  </array>
  <key>WorkingDirectory</key><string>{escape(str(workdir))}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{escape(str(log))}</string>
  <key>StandardErrorPath</key><string>{escape(str(log))}</string>
</dict>
</plist>
"""


def windows_task(cmd: list[str]) -> list[str]:
    action = subprocess.list2cmdline(cmd)
    return ["schtasks", "/Create", "/TN", NAME, "/TR", action, "/SC", "ONLOGON", "/RL", "LIMITED", "/F"]


def install(cmd: list[str], workdir: Path, runner: Runner = subprocess.run, platform: str = sys.platform,
            home: Path | None = None) -> str:  # fmt: skip
    """Install and start the service; returns what to tell the user."""
    remove_legacy(runner, platform, home)
    if platform.startswith("linux"):
        path = systemd_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(systemd_unit(cmd, workdir))
        runner(["systemctl", "--user", "daemon-reload"], check=True)
        runner(["systemctl", "--user", "enable", "--now", NAME], check=True)
        linger = runner(["loginctl", "show-user", os.environ.get("USER", ""), "--property=Linger"],
                        check=False, capture_output=True, text=True)  # fmt: skip
        note = ""
        if "Linger=yes" not in (linger.stdout or ""):
            note = "\n  To start it at boot without logging in: loginctl enable-linger"
        return f"systemd user service {path} (logs: journalctl --user -u {NAME}){note}"
    if platform == "darwin":
        path = launchd_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        log = (home or Path.home()) / "Library" / "Logs" / f"{NAME}.log"
        path.write_text(launchd_plist(cmd, workdir, log))
        runner(["launchctl", "unload", str(path)], check=False, capture_output=True)
        runner(["launchctl", "load", "-w", str(path)], check=True)
        return f"LaunchAgent {path} (logs: {log})"
    if platform == "win32":
        runner(windows_task(cmd), check=True)
        runner(["schtasks", "/Run", "/TN", NAME], check=False)
        return f"scheduled task '{NAME}' (starts when you log in)"
    raise OSError(f"don't know how to install a service on {platform}")


def remove_legacy(runner: Runner = subprocess.run, platform: str = sys.platform, home: Path | None = None) -> bool:
    """Stop and remove the service the app had under its old name; False if there was none."""
    base = home or Path.home()
    if platform.startswith("linux"):
        path = base / ".config" / "systemd" / "user" / f"{LEGACY_NAME}.service"
        if not path.exists():
            return False
        runner(["systemctl", "--user", "disable", "--now", LEGACY_NAME], check=False)
        path.unlink()
        runner(["systemctl", "--user", "daemon-reload"], check=False)
        return True
    if platform == "darwin":
        path = base / "Library" / "LaunchAgents" / f"{LEGACY_MAC_LABEL}.plist"
        if not path.exists():
            return False
        runner(["launchctl", "unload", "-w", str(path)], check=False)
        path.unlink()
        return True
    if platform == "win32":
        return runner(["schtasks", "/Delete", "/TN", LEGACY_NAME, "/F"], check=False, capture_output=True).returncode == 0
    return False


def remove(runner: Runner = subprocess.run, platform: str = sys.platform, home: Path | None = None) -> bool:
    """Stop and remove the service (also one installed under the old name); False if there was none."""
    legacy = remove_legacy(runner, platform, home)
    return _remove_current(runner, platform, home) or legacy


def _remove_current(runner: Runner, platform: str, home: Path | None) -> bool:
    if platform.startswith("linux"):
        path = systemd_path(home)
        if not path.exists():
            return False
        runner(["systemctl", "--user", "disable", "--now", NAME], check=False)
        path.unlink()
        runner(["systemctl", "--user", "daemon-reload"], check=False)
        return True
    if platform == "darwin":
        path = launchd_path(home)
        if not path.exists():
            return False
        runner(["launchctl", "unload", "-w", str(path)], check=False)
        path.unlink()
        return True
    if platform == "win32":
        return runner(["schtasks", "/Delete", "/TN", NAME, "/F"], check=False).returncode == 0
    return False

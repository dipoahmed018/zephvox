"""Microphone capture through PipeWire's `pw-record`."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from ...engine import audio
from ...engine.errors import RecordingError
from ...engine.models import SAMPLE_RATE, AudioRef
from ..base import Availability, CaptureProvider, Device, ProviderSettings


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie still "exists"; treat it as finished.
    try:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2] != "Z"
    except OSError:
        return False


class PipeWireCapture(CaptureProvider):
    name = "pipewire"

    class Settings(ProviderSettings):
        device: str | None = None  # PipeWire node name (see list_devices); None = default microphone
        stop_timeout: float = 5.0

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._proc: subprocess.Popen | None = None

    def check_available(self) -> Availability:
        if not self.services.caps.has_binary("pw-record"):
            return Availability(False, "pw-record not found (install pipewire)")
        return Availability(True)

    def capabilities(self) -> dict[str, Any]:
        return {"sample_rate": SAMPLE_RATE, "channels": 1, "detached": True}

    def list_devices(self) -> list[Device]:
        try:
            out = subprocess.run(["pw-dump"], capture_output=True, timeout=5, check=True).stdout
            objects = json.loads(out)
        except (OSError, subprocess.SubprocessError, ValueError):
            return []
        return parse_pw_dump(objects)

    def level(self, handle: dict[str, Any]) -> float | None:
        return audio.tail_level(handle["path"])

    def start(self, dest: Path) -> dict[str, Any]:
        cmd = [shutil.which("pw-record") or "pw-record", "--rate", str(SAMPLE_RATE), "--channels", "1",
               "--format", "s16"]  # fmt: skip
        if self.settings.device:
            cmd += ["--target", self.settings.device]
        cmd.append(str(dest))
        # New session: the recorder survives the CLI process that started it.
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
        return {"pid": self._proc.pid, "path": str(dest)}

    def stop(self, handle: dict[str, Any]) -> AudioRef:
        pid = int(handle["pid"])
        path = Path(handle["path"])
        if _alive(pid):
            os.kill(pid, signal.SIGINT)  # lets pw-record finalize the WAV header
            deadline = time.monotonic() + self.settings.stop_timeout
            while _alive(pid) and time.monotonic() < deadline:
                if self._proc is not None and self._proc.pid == pid:
                    try:
                        self._proc.wait(timeout=0.05)
                    except subprocess.TimeoutExpired:
                        pass
                else:
                    time.sleep(0.05)
            if _alive(pid):
                os.kill(pid, signal.SIGKILL)
        if self._proc is not None and self._proc.pid == pid:
            self._proc.wait()
            self._proc = None
        if not path.exists() or path.stat().st_size <= 44:
            raise RecordingError(f"Nothing was recorded to {path} — is a microphone connected?")
        return AudioRef(path)


def parse_pw_dump(objects: list[dict[str, Any]]) -> list[Device]:
    """Microphones (Audio/Source nodes) from `pw-dump` JSON, marking the default one."""
    default = None
    for obj in objects:
        if obj.get("type") == "PipeWire:Interface:Metadata" and (obj.get("props") or {}).get("metadata.name") == "default":
            for entry in obj.get("metadata") or []:
                if entry.get("key") == "default.audio.source":
                    value = entry.get("value")
                    default = value.get("name") if isinstance(value, dict) else None
    devices = []
    for obj in objects:
        props = (obj.get("info") or {}).get("props") or {}
        if props.get("media.class") == "Audio/Source" and props.get("node.name"):
            name = props["node.name"]
            label = props.get("node.description") or props.get("node.nick") or name
            devices.append(Device(id=name, name=label, is_default=name == default))
    return devices

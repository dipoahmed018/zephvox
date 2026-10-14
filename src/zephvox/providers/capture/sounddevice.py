"""Cross-platform microphone capture through PortAudio (`sounddevice`): Windows, macOS, Linux.

Records inside the current process, so a recording must be stopped by the process that started
it — the daemon (`zephvox serve`) or `zephvox record`.
"""

from __future__ import annotations

import importlib.util
import threading
import wave
from pathlib import Path
from typing import Any

import numpy as np

from ...engine import audio
from ...engine.errors import RecordingError
from ...engine.models import SAMPLE_RATE, AudioRef
from ..base import Availability, CaptureProvider, Device, ProviderSettings


class _Active:
    def __init__(self, stream: Any, wav: wave.Wave_write):
        self.stream = stream
        self.wav = wav
        self.level = 0.0
        self.frames = 0
        self.lock = threading.Lock()


class SoundDeviceCapture(CaptureProvider):
    name = "sounddevice"

    class Settings(ProviderSettings):
        device: str | None = None  # device name (see list_devices); None = system default

    def __init__(self, *args: Any, sd: Any = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._sd = sd  # injectable for tests
        self._active: dict[str, _Active] = {}

    def _module(self):
        if self._sd is None:
            import sounddevice

            self._sd = sounddevice
        return self._sd

    def check_available(self) -> Availability:
        if self._sd is None and importlib.util.find_spec("sounddevice") is None:
            return Availability(False, "python package 'sounddevice' not installed (uv sync --extra desktop)")
        try:
            sd = self._module()
            if not any(d["max_input_channels"] > 0 for d in sd.query_devices()):
                return Availability(False, "no input devices found")
        except Exception as e:  # PortAudio missing or broken
            return Availability(False, f"PortAudio unavailable: {e}")
        return Availability(True)

    def capabilities(self) -> dict[str, Any]:
        return {"sample_rate": SAMPLE_RATE, "channels": 1, "detached": False}

    def list_devices(self) -> list[Device]:
        sd = self._module()
        default_index = sd.default.device[0] if sd.default.device else None
        return [
            Device(id=d["name"], name=d["name"], is_default=i == default_index)
            for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0
        ]

    def start(self, dest: Path) -> dict[str, Any]:
        sd = self._module()
        wav = wave.open(str(dest), "wb")
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        active: _Active

        def callback(indata, frames, time_info, status):  # runs on PortAudio's thread
            block = np.asarray(indata, dtype=np.int16).reshape(-1)
            with active.lock:
                active.wav.writeframes(block.tobytes())
                active.frames += len(block)
                active.level = audio.level(block.astype(np.float32) / 32768)

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16", device=self.settings.device, callback=callback
        )
        active = _Active(stream, wav)
        self._active[str(dest)] = active
        stream.start()
        return {"path": str(dest)}

    def level(self, handle: dict[str, Any]) -> float | None:
        active = self._active.get(handle["path"])
        return active.level if active else None

    def stop(self, handle: dict[str, Any]) -> AudioRef:
        active = self._active.pop(handle["path"], None)
        if active is None:
            raise RecordingError("This recording belongs to another process; stop it there (e.g. the daemon)")
        active.stream.stop()
        active.stream.close()
        with active.lock:
            active.wav.close()
        if active.frames == 0:
            raise RecordingError("Nothing was recorded — is a microphone connected?")
        return AudioRef(Path(handle["path"]))

    def close(self) -> None:
        for path in list(self._active):
            try:
                self.stop({"path": path})
            except RecordingError:
                pass

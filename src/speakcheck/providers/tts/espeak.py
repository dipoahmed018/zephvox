"""Reference pronunciations spoken by espeak-ng (robotic but always available, any word)."""

from __future__ import annotations

import subprocess
from typing import Any

from ...engine.capabilities import install_hint, which
from ...engine.errors import SpeakcheckError
from ..base import Availability, ProviderSettings, TTSProvider


class EspeakTTS(TTSProvider):
    name = "espeak-ng"

    class Settings(ProviderSettings):
        voice: str = "en-us"
        speed: int = 140  # words per minute; slower than default helps learners

    def check_available(self) -> Availability:
        if not self.services.caps.has_binary("espeak-ng"):
            return Availability(False, f"espeak-ng not installed ({install_hint('espeak-ng')})")
        return Availability(True)

    def capabilities(self) -> dict[str, Any]:
        return {"voice": self.settings.voice, "format": "wav"}

    def synthesize(self, text: str) -> bytes:
        binary = which("espeak-ng") or "espeak-ng"
        cmd = [binary, "-v", self.settings.voice, "-s", str(self.settings.speed), "--stdout", text]
        proc = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
        if proc.returncode != 0 or not proc.stdout:
            raise SpeakcheckError(f"espeak-ng failed: {proc.stderr.decode(errors='replace').strip()}")
        return proc.stdout

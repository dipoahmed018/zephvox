"""Reference pronunciations spoken by espeak-ng (robotic but always available, any word)."""

from __future__ import annotations

import subprocess
from typing import Any

from ...engine.errors import SpeakcheckError
from ..base import Availability, ProviderSettings, TTSProvider


class EspeakTTS(TTSProvider):
    name = "espeak-ng"

    class Settings(ProviderSettings):
        voice: str = "en-us"
        speed: int = 140  # words per minute; slower than default helps learners

    def check_available(self) -> Availability:
        if not self.services.caps.has_binary("espeak-ng"):
            return Availability(False, "espeak-ng not installed")
        return Availability(True)

    def capabilities(self) -> dict[str, Any]:
        return {"voice": self.settings.voice, "format": "wav"}

    def synthesize(self, text: str) -> bytes:
        cmd = ["espeak-ng", "-v", self.settings.voice, "-s", str(self.settings.speed), "--stdout", text]
        proc = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
        if proc.returncode != 0 or not proc.stdout:
            raise SpeakcheckError(f"espeak-ng failed: {proc.stderr.decode(errors='replace').strip()}")
        return proc.stdout

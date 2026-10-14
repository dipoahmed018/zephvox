"""Synthesize test recordings with espeak-ng, including deliberate mistakes.

espeak-ng's [[...]] phoneme input lets us say a word *wrongly* on purpose, e.g. "think" as
"sink", so integration tests can assert that a specific mistake is found.

    uv run python scripts/make_fixtures.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# name -> text spoken by espeak-ng (en-us). [[...]] = raw espeak phonemes.
CLIPS = {
    # Correct speech: should produce no pronunciation findings for content words.
    "clean": "I think we should go to the market today. The weather is very nice.",
    # "think" → /sɪŋk/, "very" → /wɛɹi/.
    "mispronounced": "I [[s'INk]] we should go now. The weather is [[w'Eri]] nice.",
    # Grammar errors, pronounced correctly.
    "grammar": "Yesterday he go to the market. She have two cat.",
}


def main() -> int:
    if shutil.which("espeak-ng") is None:
        print("espeak-ng is not installed (sudo pacman -S espeak-ng)", file=sys.stderr)
        return 1
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, text in CLIPS.items():
        raw = FIXTURES / f"{name}.raw.wav"
        out = FIXTURES / f"{name}.wav"
        subprocess.run(["espeak-ng", "-v", "en-us", "-s", "140", "-w", str(raw), text], check=True)
        # Resample to the engine's 16 kHz mono.
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-ac", "1", "-ar", "16000", str(out)],
                       check=True)  # fmt: skip
        raw.unlink()
        print(f"wrote {out.relative_to(FIXTURES.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

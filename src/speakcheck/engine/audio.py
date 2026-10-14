"""Audio I/O. Everything inside the engine is 16 kHz mono float32."""

from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path
from typing import BinaryIO

import numpy as np

from .errors import AudioError
from .models import SAMPLE_RATE


def decode(path: Path | str, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Decode any audio file ffmpeg understands into mono float32 samples."""
    path = Path(path)
    if not path.exists():
        raise AudioError(f"Audio file not found: {path}")
    if shutil.which("ffmpeg") is None:
        raise AudioError("ffmpeg is required to read audio files")
    cmd = [
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
        "-f", "f32le", "-ac", "1", "-ar", str(sample_rate), "-",
    ]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise AudioError(f"ffmpeg could not decode {path}: {proc.stderr.decode(errors='replace').strip()}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def write_wav(path: Path | str | BinaryIO, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(path if hasattr(path, "write") else str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(pcm.tobytes())


def slice_seconds(samples: np.ndarray, start: float, end: float, pad: float = 0.0,
                  sample_rate: int = SAMPLE_RATE) -> np.ndarray:  # fmt: skip
    lo = max(0, int((start - pad) * sample_rate))
    hi = min(len(samples), int((end + pad) * sample_rate))
    return samples[lo:hi]


def duration(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    return len(samples) / sample_rate


def level(samples: np.ndarray) -> float:
    """Loudness of a short block as 0–1 for meters (-60 dBFS → 0, 0 dBFS → 1)."""
    if len(samples) == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    if rms <= 1e-6:
        return 0.0
    return float(np.clip((20 * np.log10(rms) + 60) / 60, 0.0, 1.0))


def tail_level(path: Path | str, seconds: float = 0.1, sample_rate: int = SAMPLE_RATE) -> float | None:
    """Level of the last `seconds` of a 16-bit mono WAV that is still being written."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            want = int(seconds * sample_rate) * 2
            if size <= 44:
                return 0.0
            f.seek(max(44, size - want))
            data = f.read(want)
    except OSError:
        return None
    data = data[: len(data) - len(data) % 2]
    return level(np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768)

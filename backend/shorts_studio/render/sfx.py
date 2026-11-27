# Portions adapted from PurffleShorts (MIT), © 2025 Purffle, commit 514fd25: purffle_shorts/sfx.py
# (`whoosh`, `pop`, `hit` synthesis). Changes: fixed seeds so the preview and the export hear the same effect,
# three more effects (ding, boing, record_scratch), one WAV file per effect.
"""Sound effects synthesised from noise and sine waves: nothing to download or license."""
from __future__ import annotations

import math
import random
import wave
from array import array
from pathlib import Path

RATE = 48000
PEAK = 0.5
SOUNDS = ("whoosh", "pop", "hit", "ding", "boing", "record_scratch")


def _normalise(x: list[float], peak: float = PEAK) -> list[float]:
    m = max((abs(v) for v in x), default=0.0)
    return [v * peak / m for v in x] if m > 0 else x


def whoosh(rng: random.Random, seconds: float = 0.5) -> list[float]:
    n = int(seconds * RATE)
    lo, top = rng.uniform(280, 420), rng.uniform(2200, 3200)
    peak_at = 0.22 / seconds
    low = band = 0.0
    out = []
    for i in range(n):
        p = i / n
        sweep = p / peak_at if p < peak_at else 1 - (p - peak_at) / (1 - peak_at) * 0.85
        fc = lo + (top - lo) * sweep * sweep
        f = 2 * math.sin(math.pi * fc / RATE)
        low += f * band
        high = rng.uniform(-1.0, 1.0) - low - 0.55 * band
        band += f * high
        envl = math.sin(0.5 * math.pi * p / peak_at) ** 2 if p < peak_at else math.exp(-4.5 * (p - peak_at) / (1 - peak_at))
        out.append(band * envl)
    return _normalise(out)


def pop(rng: random.Random, seconds: float = 0.09) -> list[float]:
    n = int(seconds * RATE)
    f0, f1 = rng.uniform(1250, 1500), rng.uniform(330, 420)
    phase, out = 0.0, []
    for i in range(n):
        t = i / RATE
        phase += 2 * math.pi * (f1 + (f0 - f1) * math.exp(-t / 0.012)) / RATE
        out.append(math.sin(phase) * math.exp(-t / 0.022) + rng.uniform(-0.3, 0.3) * math.exp(-t / 0.0015))
    return _normalise(out, PEAK * 0.8)


def hit(rng: random.Random, seconds: float = 0.65) -> list[float]:
    n = int(seconds * RATE)
    f0, f1 = rng.uniform(140, 170), rng.uniform(55, 65)
    phase, low, out = 0.0, 0.0, []
    a = 1 - math.exp(-2 * math.pi * 900 / RATE)
    for i in range(n):
        t = i / RATE
        phase += 2 * math.pi * (f1 + (f0 - f1) * math.exp(-t / 0.06)) / RATE
        low += a * (rng.uniform(-1.0, 1.0) - low)
        out.append(math.sin(phase) * math.exp(-t / 0.22) + low * 1.8 * math.exp(-t / 0.035))
    return _normalise(out)


def ding(rng: random.Random, seconds: float = 0.9) -> list[float]:
    """A small bell: two inharmonic partials with a slow decay."""
    n = int(seconds * RATE)
    f = rng.uniform(1180, 1260)
    out = [(math.sin(2 * math.pi * f * i / RATE) + 0.45 * math.sin(2 * math.pi * f * 2.76 * i / RATE))
           * math.exp(-i / RATE / 0.25) for i in range(n)]
    return _normalise(out, PEAK * 0.8)


def boing(rng: random.Random, seconds: float = 0.6) -> list[float]:
    """A spring: a wobbling pitch that slides up."""
    n = int(seconds * RATE)
    base = rng.uniform(180, 220)
    phase, out = 0.0, []
    for i in range(n):
        t = i / RATE
        fc = base * (1 + 1.6 * t / seconds) * (1 + 0.18 * math.sin(2 * math.pi * 14 * t))
        phase += 2 * math.pi * fc / RATE
        out.append(math.sin(phase) * math.exp(-t / 0.3))
    return _normalise(out)


def record_scratch(rng: random.Random, seconds: float = 0.45) -> list[float]:
    """Filtered noise whose pitch rocks back and forth fast, like a record pulled by hand."""
    n = int(seconds * RATE)
    low = band = 0.0
    out = []
    for i in range(n):
        t = i / RATE
        fc = 900 + 700 * math.sin(2 * math.pi * 9 * t)
        f = 2 * math.sin(math.pi * fc / RATE)
        low += f * band
        high = rng.uniform(-1.0, 1.0) - low - 0.3 * band
        band += f * high
        out.append(band * min(1.0, t / 0.02) * math.exp(-t / 0.25))
    return _normalise(out)


_SYNTHS = {"whoosh": whoosh, "pop": pop, "hit": hit, "ding": ding, "boing": boing, "record_scratch": record_scratch}


def ensure(folder: Path, name: str) -> Path:
    """The effect's WAV file, synthesised once with a fixed seed."""
    if name not in _SYNTHS:
        raise KeyError(name)
    dest = folder / f"{name}.wav"
    if dest.is_file():
        return dest
    folder.mkdir(parents=True, exist_ok=True)
    samples = _SYNTHS[name](random.Random(f"shorts-studio-{name}"))
    pcm = array("h", (max(-32767, min(32767, int(v * 32767))) for v in samples))
    tmp = dest.with_suffix(".part.wav")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    tmp.replace(dest)
    return dest

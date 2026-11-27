"""Owned test media made entirely by FFmpeg (no third-party footage).

``bands_video`` draws six vertical colour bands so a crop can be checked by sampling one pixel, a strip of
FFmpeg's ``testsrc`` along the top for motion, a white marker that sweeps across at a known speed (so the source
time of any output frame can be measured), and a tone with a short beep at every whole second.
"""
from __future__ import annotations

from pathlib import Path

from .render.ffmpeg import run

BAND_COLORS = [("red", (255, 0, 0)), ("yellow", (255, 255, 0)), ("lime", (0, 255, 0)),
               ("cyan", (0, 255, 255)), ("blue", (0, 0, 255)), ("magenta", (255, 0, 255))]
# A white marker sweeps left to right so a frame's source time can be read from its position:
# x = (MARKER_SPEED * t) mod (width - MARKER_W), on rows MARKER_Y .. MARKER_Y + MARKER_H/height.
MARKER_SPEED = 240
MARKER_W, MARKER_H = 8, 60
MARKER_Y = 0.87


def marker_x(t: float, width: int = 1920) -> float:
    """Centre column of the marker at source time ``t``."""
    return (MARKER_SPEED * t) % (width - MARKER_W) + MARKER_W / 2


def bands_video(dest: Path, *, seconds: float = 30, fps: int = 30, size: tuple[int, int] = (1920, 1080),
                audio: bool = True, rotation: int | None = None, codec: str = "libx264") -> Path:
    W, H = size
    band = W // len(BAND_COLORS)
    strip = max(64, H // 6 // 2 * 2)
    args: list[str] = []
    for name, _rgb in BAND_COLORS:
        args += ["-f", "lavfi", "-i", f"color=c={name}:s={band}x{H}:r={fps}:d={seconds}"]
    args += ["-f", "lavfi", "-i", f"testsrc=s={band * len(BAND_COLORS)}x{strip}:r={fps}:d={seconds}"]
    args += ["-f", "lavfi", "-i", f"color=c=white:s={MARKER_W}x{MARKER_H}:r={fps}:d={seconds}"]
    n = len(BAND_COLORS)
    my = int(H * MARKER_Y)
    graph = ("".join(f"[{i}:v]" for i in range(n)) + f"hstack=inputs={n}[b];[b][{n}:v]overlay=0:0[s];"
             f"[s][{n + 1}:v]overlay=x='mod({MARKER_SPEED}*t,{W - MARKER_W})':y={my},format=yuv420p[v]")
    maps = ["-map", "[v]"]
    if audio:
        expr = "0.12*sin(2*PI*440*t)+0.25*sin(2*PI*880*t)*lt(mod(t\\,1)\\,0.12)"
        args += ["-f", "lavfi", "-i", f"aevalsrc={expr}|{expr}:s=48000:d={seconds}"]
        maps += ["-map", f"{n + 2}:a"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".part" + dest.suffix)
    venc = (["-c:v", "libx265", "-preset", "fast", "-crf", "22", "-tag:v", "hvc1", "-x265-params", "log-level=error"]
            if codec == "libx265" else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"])
    run([*args, "-filter_complex", graph, *maps, *venc, "-g", str(fps),
         *(["-c:a", "aac", "-b:a", "160k"] if audio else []), "-t", str(seconds), str(tmp)],
        label="test media", timeout=900)
    if rotation:
        rotated = dest.with_name(dest.stem + ".rot" + dest.suffix)
        run(["-display_rotation", str(rotation), "-i", str(tmp), "-c", "copy", str(rotated)], label="rotate", timeout=120)
        tmp.unlink()
        tmp = rotated
    tmp.replace(dest)
    return dest


def solid_video(dest: Path, color: str, *, seconds: float = 6, fps: int = 30, size: tuple[int, int] = (1920, 1080),
                tone_hz: int | None = 330) -> Path:
    """One flat colour (easy to recognise in a frame) with an optional steady tone."""
    W, H = size
    args = ["-f", "lavfi", "-i", f"color=c={color}:s={W}x{H}:r={fps}:d={seconds}"]
    maps = ["-map", "0:v"]
    if tone_hz:
        args += ["-f", "lavfi", "-i", f"sine=frequency={tone_hz}:sample_rate=48000:duration={seconds}"]
        maps += ["-map", "1:a"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".part" + dest.suffix)
    run([*args, *maps, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-g", str(fps),
         *(["-c:a", "aac", "-b:a", "128k", "-af", "volume=-12dB"] if tone_hz else []), "-t", str(seconds), str(tmp)],
        label="test media", timeout=300)
    tmp.replace(dest)
    return dest


def classify(rgb: tuple[int, int, int]) -> str:
    """Nearest band colour (video encoding shifts colours a little)."""
    return min(BAND_COLORS, key=lambda c: sum((a - b) ** 2 for a, b in zip(c[1], rgb)))[0]


def band_at(x: float, width: int = 1920) -> str:
    """The band colour at source column ``x``."""
    band = width // len(BAND_COLORS)
    return BAND_COLORS[min(len(BAND_COLORS) - 1, int(x // band))][0]

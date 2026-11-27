"""Posters, filmstrips and preview proxies. All are derived from the original and can be deleted at any time."""
from __future__ import annotations

from pathlib import Path

from ..render.ffmpeg import CancelToken, run

FILMSTRIP_FRAMES = 24
FILMSTRIP_W, FILMSTRIP_H = 160, 90
PROXY_LONG_SIDE = 1280


def poster(src: Path, kind: str, duration: float | None, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".part.jpg")
    seek = ["-ss", f"{min(1.0, (duration or 0) * 0.1):.3f}"] if kind == "video" else []
    run([*seek, "-i", str(src), "-frames:v", "1", "-vf", "scale=320:320:force_original_aspect_ratio=decrease",
         "-q:v", "4", str(tmp)], label="poster", timeout=60)
    tmp.replace(dest)
    return dest


def filmstrip(src: Path, duration: float, dest: Path, frames: int = FILMSTRIP_FRAMES) -> Path:
    """``frames`` thumbnails side by side, one from the middle of each equal slice of the video."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".part.jpg")
    n = max(1, min(frames, int(duration * 2) or 1))
    args: list[str] = []
    chains = []
    for i in range(n):
        t = duration * (i + 0.5) / n
        args += ["-ss", f"{t:.3f}", "-i", str(src)]
        chains.append(f"[{i}:v]scale={FILMSTRIP_W}:{FILMSTRIP_H}:force_original_aspect_ratio=decrease,"
                      f"pad={FILMSTRIP_W}:{FILMSTRIP_H}:(ow-iw)/2:(oh-ih)/2,setsar=1,trim=end_frame=1[f{i}]")
    if n == 1:
        graph = chains[0].replace("[f0]", "[out]")
    else:
        graph = ";".join(chains) + ";" + "".join(f"[f{i}]" for i in range(n)) + f"hstack=inputs={n}[out]"
    run([*args, "-filter_complex", graph, "-map", "[out]", "-frames:v", "1", "-q:v", "5", str(tmp)],
        label="filmstrip", timeout=180)
    tmp.replace(dest)
    return dest


def proxy(src: Path, duration: float, dest: Path, *, cancel: CancelToken | None = None, progress=None) -> Path:
    """A small H.264 copy that every browser can scrub: long side 1280, a keyframe every 0.5 s."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".part.mp4")
    vf = (f"scale='if(gte(iw,ih),min({PROXY_LONG_SIDE},iw),-2)':'if(gte(iw,ih),-2,min({PROXY_LONG_SIDE},ih))'"
          ",format=yuv420p")
    run(["-i", str(src), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-g", "15",
         "-keyint_min", "15", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart", str(tmp)],
        label="preview proxy", cancel=cancel, progress=progress, duration=duration, timeout=6 * 3600)
    tmp.replace(dest)
    return dest

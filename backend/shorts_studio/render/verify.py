"""Check a finished MP4 against what the project asked for, before calling the render done."""
from __future__ import annotations

from pathlib import Path

from .ffmpeg import CancelToken, ebur128_summary, probe_json, run

LOUDNESS_TOLERANCE_LU = 1.0


def _rate(value: str | None) -> float | None:
    if not value or "/" not in value:
        return None
    num, den = value.split("/", 1)
    return float(num) / float(den) if float(den) else None


def moov_before_mdat(path: Path) -> bool:
    """True when the MP4 index is at the front (``-movflags +faststart``), so playback starts before download ends."""
    with path.open("rb") as f:
        pos = 0
        size_total = path.stat().st_size
        while pos < size_total:
            f.seek(pos)
            header = f.read(16)
            if len(header) < 8:
                return False
            size = int.from_bytes(header[:4], "big")
            kind = header[4:8]
            if size == 1:
                size = int.from_bytes(header[8:16], "big")
            if kind == b"moov":
                return True
            if kind == b"mdat":
                return False
            if size < 8:
                return False
            pos += size
    return False


def measure_loudness(path: Path, cancel: CancelToken | None = None, stream: str = "0:a:0") -> dict:
    err = run(["-i", str(path), "-map", stream, "-af", "ebur128=peak=true", "-f", "null", "-"],
              label="measuring loudness", loglevel="info", cancel=cancel)
    return ebur128_summary(err)


def verify(path: Path, *, width: int, height: int, fps: int, frames: int, expect_audio: bool,
           audio_sample_rate: int = 48000, loudness_target: float | None = None, audio_silent: bool = False,
           cancel: CancelToken | None = None) -> dict:
    checks: list[dict] = []

    def check(name: str, ok: bool, expected, actual, severity: str = "error") -> None:
        checks.append({"name": name, "ok": bool(ok), "expected": expected, "actual": actual, "severity": severity})

    info = probe_json(path, count_packets=True)
    fmt = info.get("format") or {}
    streams = info.get("streams") or []
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    check("container", "mp4" in (fmt.get("format_name") or ""), "mp4", fmt.get("format_name"))
    check("video streams", len(video) == 1, 1, len(video))
    summary: dict = {"size_bytes": int(fmt.get("size") or 0), "duration_s": float(fmt.get("duration") or 0)}
    if video:
        v = video[0]
        rate = _rate(v.get("avg_frame_rate"))
        packets = int(v.get("nb_read_packets") or 0)
        vdur = float(v.get("duration") or fmt.get("duration") or 0)
        check("video codec", v.get("codec_name") == "h264", "h264", v.get("codec_name"))
        check("width", v.get("width") == width, width, v.get("width"))
        check("height", v.get("height") == height, height, v.get("height"))
        check("pixel format", v.get("pix_fmt") == "yuv420p", "yuv420p", v.get("pix_fmt"))
        sar = v.get("sample_aspect_ratio") or "1:1"
        check("square pixels", sar in ("1:1", "0:1"), "1:1", sar)
        check("frame rate", rate is not None and abs(rate - fps) < 0.01, fps, round(rate, 3) if rate else None)
        check("frame count", packets == frames, frames, packets)
        check("video duration", abs(vdur - frames / fps) <= 1.0 / fps + 1e-3, round(frames / fps, 3), round(vdur, 3))
        summary.update({"width": v.get("width"), "height": v.get("height"), "fps": round(rate, 3) if rate else None,
                        "frames": packets, "video_codec": v.get("codec_name"), "pix_fmt": v.get("pix_fmt"),
                        "video_duration_s": round(vdur, 3)})
    check("audio streams", len(audio) == (1 if expect_audio else 0), 1 if expect_audio else 0, len(audio))
    summary["audio_streams"] = len(audio)
    if audio and expect_audio:
        a = audio[0]
        check("audio codec", a.get("codec_name") == "aac", "aac", a.get("codec_name"))
        check("audio sample rate", int(a.get("sample_rate") or 0) == audio_sample_rate, audio_sample_rate,
              int(a.get("sample_rate") or 0))
        check("audio channels", a.get("channels") == 2, 2, a.get("channels"))
        summary.update({"audio_codec": a.get("codec_name"), "audio_sample_rate": int(a.get("sample_rate") or 0),
                        "audio_channels": a.get("channels")})
        if loudness_target is not None:
            loud = measure_loudness(path, cancel)
            summary["loudness"] = loud
            lufs = loud.get("integrated_lufs")
            if audio_silent:
                check("loudness", True, "silent audio (not normalised)", lufs, "warning")
            else:
                check("loudness", lufs is not None and abs(lufs - loudness_target) <= LOUDNESS_TOLERANCE_LU,
                      f"{loudness_target} ±{LOUDNESS_TOLERANCE_LU} LUFS", lufs)
    check("fast start", moov_before_mdat(path), True, moov_before_mdat(path))
    failed = [c for c in checks if not c["ok"] and c["severity"] == "error"]
    return {"ok": not failed, "checks": checks, "failed": [c["name"] for c in failed], "summary": summary}

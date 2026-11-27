"""ffprobe a file and build the fingerprint stored in the project (see schema $defs/fingerprint)."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from ..render.ffmpeg import FFmpegError, probe_json

SAMPLE_BYTES = 1 << 20          # 1 MiB from the start and from the end
IMAGE_CODECS = {"png", "mjpeg", "jpegls", "webp", "bmp", "tiff", "gif", "jpeg2000"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".m2ts", ".ts", ".wmv", ".flv", ".3gp"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | VIDEO_SUFFIXES | AUDIO_SUFFIXES


class ProbeError(Exception):
    pass


def sample_sha256(path: Path) -> str:
    size = path.stat().st_size
    h = hashlib.sha256()
    h.update(str(size).encode())
    with path.open("rb") as f:
        h.update(f.read(SAMPLE_BYTES))
        if size > SAMPLE_BYTES:
            f.seek(max(SAMPLE_BYTES, size - SAMPLE_BYTES))
            h.update(f.read(SAMPLE_BYTES))
    return h.hexdigest()


def _rate(value: str | None) -> float | None:
    if not value or value in ("0/0", "0"):
        return None
    if "/" in value:
        num, den = value.split("/", 1)
        try:
            return round(float(num) / float(den), 3) if float(den) else None
        except ValueError:
            return None
    try:
        return float(value)
    except ValueError:
        return None


def _rotation(stream: dict) -> int:
    raw = None
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            raw = side["rotation"]
            break
    if raw is None:
        raw = (stream.get("tags") or {}).get("rotate")
    try:
        deg = int(round(float(raw or 0)))
    except (TypeError, ValueError):
        deg = 0
    deg = (-deg) % 360
    return min((0, 90, 180, 270), key=lambda r: min(abs(deg - r), 360 - abs(deg - r)))


def probe_file(path: Path) -> tuple[str, dict, dict]:
    """Return (kind, fingerprint, extra). ``extra`` holds facts the app needs but the project does not store."""
    if not path.is_file():
        raise ProbeError(f"{path} is not a file.")
    try:
        info = probe_json(path)
    except FFmpegError as e:
        raise ProbeError(str(e)) from e
    streams = info.get("streams") or []
    fmt = info.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    suffix = path.suffix.lower()

    duration = None
    for candidate in (fmt.get("duration"), (video or {}).get("duration"), (audio or {}).get("duration")):
        try:
            if candidate is not None and float(candidate) > 0:
                duration = round(float(candidate), 3)
                break
        except ValueError:
            continue

    if video is not None and (video.get("codec_name") in IMAGE_CODECS and (suffix in IMAGE_SUFFIXES or not duration
                                                                        or int(video.get("nb_frames") or 0) <= 1)):
        kind = "image"
        duration = None
    elif video is not None:
        kind = "video"
    elif audio is not None:
        kind = "audio"
    else:
        raise ProbeError(f"{path.name} has no picture or sound that FFmpeg can read.")
    if kind == "video" and not duration:
        raise ProbeError(f"{path.name} has no readable duration.")

    st = path.stat()
    fingerprint = {
        "size_bytes": st.st_size,
        "mtime": round(st.st_mtime, 3),
        "sample_sha256": sample_sha256(path),
        "duration_s": duration,
        "width": int(video["width"]) if video and video.get("width") else None,
        "height": int(video["height"]) if video and video.get("height") else None,
        "fps": _rate((video or {}).get("avg_frame_rate")) or _rate((video or {}).get("r_frame_rate")) if kind == "video" else None,
        "rotation": _rotation(video) if video else 0,
        "has_audio": audio is not None,
        "video_codec": (video or {}).get("codec_name"),
        "audio_codec": (audio or {}).get("codec_name"),
    }
    extra = {
        "container": fmt.get("format_name"),
        "pix_fmt": (video or {}).get("pix_fmt"),
        "bit_rate": int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None,
        "audio_channels": (audio or {}).get("channels"),
        "audio_sample_rate": int(audio["sample_rate"]) if audio and str(audio.get("sample_rate", "")).isdigit() else None,
    }
    return kind, fingerprint, extra


def display_size(fingerprint: dict) -> tuple[int, int] | None:
    """Width/height as shown, after the rotation flag (FFmpeg and browsers both apply it)."""
    w, h = fingerprint.get("width"), fingerprint.get("height")
    if not w or not h:
        return None
    return (h, w) if fingerprint.get("rotation") in (90, 270) else (w, h)


def needs_proxy(kind: str, fingerprint: dict, extra: dict) -> bool:
    """Browsers play 8-bit 4:2:0 H.264 up to 1080p smoothly; anything else gets a preview proxy."""
    if kind != "video":
        return False
    size = display_size(fingerprint) or (0, 0)
    if max(size) > 1920:
        return True
    if fingerprint.get("video_codec") != "h264":
        return True
    if extra.get("pix_fmt") not in ("yuv420p", "yuvj420p"):
        return True
    container = extra.get("container") or ""
    return not any(c in container for c in ("mp4", "mov"))


def file_stat_matches(path: Path, fingerprint: dict) -> bool:
    try:
        st = os.stat(path)
    except OSError:
        return False
    return st.st_size == fingerprint["size_bytes"] and abs(st.st_mtime - fingerprint["mtime"]) < 0.01

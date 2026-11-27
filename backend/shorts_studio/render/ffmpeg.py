# Portions adapted from PurffleShorts (MIT), © 2025 Purffle, commit 514fd25: purffle_shorts/ffmpeg.py
# (`ffmpeg_bin`, `ffprobe_bin`, `run` progress parsing and kill-on-cancel, `loudnorm_report`).
# Changes: a per-job CancelToken instead of a global event, ffprobe JSON passthrough, no imageio fallback.
"""Locate and drive ffmpeg / ffprobe. Every call uses an argument list, never a shell string."""
from __future__ import annotations

import functools
import json
import logging
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("shorts_studio.ffmpeg")

# Windows: don't flash a console window for every child process when running under pythonw.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FFmpegError(RuntimeError):
    pass


class Cancelled(Exception):
    pass


class CancelToken:
    """Shared between a job and the processes it starts. ``cancel()`` kills the running process."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._procs: set[subprocess.Popen] = set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            procs = list(self._procs)
        for p in procs:
            try:
                p.kill()
            except OSError:
                pass

    def check(self, label: str = "job") -> None:
        if self._event.is_set():
            raise Cancelled(label)

    def _add(self, p: subprocess.Popen) -> None:
        with self._lock:
            self._procs.add(p)
        if self._event.is_set():
            p.kill()

    def _discard(self, p: subprocess.Popen) -> None:
        with self._lock:
            self._procs.discard(p)


@functools.lru_cache(maxsize=1)
def ffmpeg_bin() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise FFmpegError("FFmpeg was not found on PATH. Install it (winget install Gyan.FFmpeg, or brew install ffmpeg).")
    return found


@functools.lru_cache(maxsize=1)
def ffprobe_bin() -> str:
    found = shutil.which("ffprobe")
    if found:
        return found
    sibling = Path(ffmpeg_bin()).with_name("ffprobe" + Path(ffmpeg_bin()).suffix)
    if sibling.exists():
        return str(sibling)
    raise FFmpegError("ffprobe was not found on PATH.")


@functools.lru_cache(maxsize=1)
def version() -> str:
    out = subprocess.run([ffmpeg_bin(), "-hide_banner", "-version"], capture_output=True, text=True,
                         creationflags=_NO_WINDOW).stdout
    m = re.search(r"ffmpeg version (\S+)", out)
    return m.group(1) if m else "unknown"


def run(args: list[str], *, label: str = "ffmpeg", timeout: float = 3600, loglevel: str = "error",
        progress: Callable[[float], None] | None = None, duration: float = 0.0,
        cancel: CancelToken | None = None) -> str:
    """Run ffmpeg; return its stderr (with ``loglevel="info"`` that includes filter reports such as loudnorm).

    With ``progress`` and the expected output ``duration``, ``progress`` receives 0..1 about twice a second."""
    watch = progress is not None and duration > 0
    extra = ["-nostats", "-progress", "pipe:1"] if watch else ["-nostats"]
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", loglevel, *extra, "-y", *args]
    log.debug("%s: %s", label, subprocess.list2cmdline(cmd))
    if cancel is not None:
        cancel.check(label)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE if watch else subprocess.DEVNULL, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                            creationflags=_NO_WINDOW)
    if cancel is not None:
        cancel._add(proc)
    deadline = time.monotonic() + timeout
    stderr = ""
    timed_out = False
    try:
        if watch:
            err: list[str] = []
            reader = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
            reader.start()
            for line in proc.stdout:
                key, _, value = line.strip().partition("=")
                if key in ("out_time_us", "out_time_ms") and value.lstrip("-").isdigit():
                    try:
                        progress(max(0.0, min(1.0, int(value) / 1e6 / duration)))
                    except Exception:  # a progress display must never break a render
                        log.debug("progress callback failed", exc_info=True)
                if time.monotonic() > deadline:
                    timed_out = True
                    proc.kill()
            proc.wait()
            reader.join(timeout=5)
            stderr = "".join(err)
        else:
            while True:
                try:
                    stderr = proc.communicate(timeout=0.5)[1] or ""
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() > deadline:
                        timed_out = True
                        proc.kill()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if cancel is not None:
            cancel._discard(proc)
    if cancel is not None and cancel.cancelled:
        raise Cancelled(label)
    if timed_out:
        raise FFmpegError(f"{label} took longer than {int(timeout)} s and was stopped.")
    if proc.returncode != 0:
        tail = "\n".join(stderr.strip().splitlines()[-12:])
        raise FFmpegError(f"{label} failed (exit {proc.returncode}):\n{tail}")
    return stderr


def probe_json(path: str | Path, *, count_packets: bool = False, timeout: float = 120) -> dict:
    """Full ffprobe report (format + streams) as a dict."""
    cmd = [ffprobe_bin(), "-v", "error", "-show_format", "-show_streams", "-of", "json"]
    if count_packets:
        cmd.insert(3, "-count_packets")
    cmd.append(str(path))
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=timeout, creationflags=_NO_WINDOW)
    if out.returncode != 0:
        raise FFmpegError(f"ffprobe could not read {Path(path).name}: {out.stderr.strip()[-300:]}")
    return json.loads(out.stdout or "{}")


def loudnorm_report(stderr: str) -> dict | None:
    """The JSON block that ``loudnorm=print_format=json`` writes at the end of a run."""
    end = stderr.rfind("}")
    start = stderr.rfind("{", 0, end)
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(stderr[start:end + 1])
    except ValueError:
        return None


def ebur128_summary(stderr: str) -> dict:
    """Integrated loudness (LUFS), loudness range and true peak from an ``ebur128=peak=true`` run."""
    tail = stderr[stderr.rfind("Summary:"):] if "Summary:" in stderr else stderr
    out: dict = {}
    m = re.search(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", tail)
    if m:
        out["integrated_lufs"] = float(m.group(1)) if m.group(1) != "-inf" else float("-inf")
    m = re.search(r"LRA:\s+(-?[\d.]+)\s+LU", tail)
    if m:
        out["lra_lu"] = float(m.group(1))
    m = re.search(r"True peak:\s+Peak:\s+(-?[\d.]+|-inf)\s+dBFS", tail)
    if m:
        out["true_peak_dbfs"] = float(m.group(1)) if m.group(1) != "-inf" else float("-inf")
    return out

# Portions adapted from PurffleShorts (MIT), © 2025 Purffle, commit 514fd25: purffle_shorts/tts.py
# (Edge TTS with WordBoundary events, the operating-system voice as an offline fallback).
"""Text-to-speech engines. Each returns (audio file, [Word] with native timings or None, voice name)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from ..timeline.words import Word

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SAPI_SCRIPT = Path(__file__).with_name("sapi.ps1")

# Shown when the Edge voice list can't be fetched (offline). All are free Microsoft neural voices.
EDGE_FALLBACK = [
    {"id": "en-US-AndrewNeural", "name": "Andrew", "locale": "en-US", "gender": "Male"},
    {"id": "en-US-AvaNeural", "name": "Ava", "locale": "en-US", "gender": "Female"},
    {"id": "en-US-BrianNeural", "name": "Brian", "locale": "en-US", "gender": "Male"},
    {"id": "en-US-EmmaNeural", "name": "Emma", "locale": "en-US", "gender": "Female"},
    {"id": "en-US-GuyNeural", "name": "Guy", "locale": "en-US", "gender": "Male"},
    {"id": "en-US-JennyNeural", "name": "Jenny", "locale": "en-US", "gender": "Female"},
    {"id": "en-CA-LiamNeural", "name": "Liam", "locale": "en-CA", "gender": "Male"},
    {"id": "en-CA-ClaraNeural", "name": "Clara", "locale": "en-CA", "gender": "Female"},
    {"id": "en-GB-RyanNeural", "name": "Ryan", "locale": "en-GB", "gender": "Male"},
    {"id": "en-GB-SoniaNeural", "name": "Sonia", "locale": "en-GB", "gender": "Female"},
    {"id": "en-GB-ThomasNeural", "name": "Thomas", "locale": "en-GB", "gender": "Male"},
    {"id": "en-GB-LibbyNeural", "name": "Libby", "locale": "en-GB", "gender": "Female"},
]
# British voices are offered too, for a British accent; the audience setting (US/CA) still sets spelling and units.
EDGE_LOCALES = ("en-US", "en-CA", "en-GB")


class SpeechError(Exception):
    pass


def edge(text: str, voice: str, rate_pct: int, out_dir: Path) -> tuple[Path, list[Word], str]:
    try:
        import edge_tts
    except ImportError as e:  # pragma: no cover
        raise SpeechError("Edge TTS is not installed (pip install edge-tts).") from e
    path = out_dir / "edge.mp3"
    words: list[Word] = []
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            words = []
            comm = edge_tts.Communicate(text, voice, rate=f"{rate_pct:+d}%", boundary="WordBoundary",
                                        receive_timeout=60)
            with path.open("wb") as f:
                for chunk in comm.stream_sync():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        start = chunk["offset"] / 1e7
                        words.append(Word(chunk["text"], round(start, 3), round(start + chunk["duration"] / 1e7, 3)))
            if path.stat().st_size == 0:
                raise SpeechError("Edge TTS returned no audio.")
            return path, words, voice
        except Exception as e:  # noqa: BLE001 - network hiccups are retried
            last_error = e
            time.sleep(1.5 * (attempt + 1))
    raise SpeechError(f"Edge TTS failed (it needs an internet connection): {last_error}")


def system(text: str, voice: str, rate_pct: int, out_dir: Path) -> tuple[Path, list[Word] | None, str]:
    """The operating system's own voice. Works offline. Windows also reports when each word starts."""
    if sys.platform == "win32":
        txt = out_dir / "text.txt"
        txt.write_text(text, encoding="utf-8")
        out = out_dir / "system.wav"
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SAPI_SCRIPT),
                "-TextFile", str(txt), "-Out", str(out), "-Rate", str(round(rate_pct / 10))]
        if voice:
            args += ["-Voice", voice]
        proc = subprocess.run(args, capture_output=True, text=True, timeout=300, creationflags=_NO_WINDOW)
        if proc.returncode != 0 or not out.is_file():
            raise SpeechError("The Windows voice failed: " + (proc.stderr or proc.stdout).strip()[-400:])
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        starts = [(w["text"], w["ms"] / 1000.0) for w in data["words"]]
        words = []
        for k, (t, s) in enumerate(starts):
            end = starts[k + 1][1] - 0.02 if k + 1 < len(starts) else s + 0.1 + 0.06 * len(t)
            words.append(Word(t, round(s, 3), round(max(s + 0.04, end), 3)))
        return out, words, data.get("voice") or voice
    if sys.platform == "darwin":
        out = out_dir / "system.aiff"
        args = ["say", "-o", str(out)]
        if voice:
            args += ["-v", voice]
        args += ["-r", str(int(175 * (1 + rate_pct / 100))), text]
        proc = subprocess.run(args, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise SpeechError("The macOS voice failed: " + proc.stderr.strip()[-300:])
        return out, None, voice or "default"
    raise SpeechError("No offline system voice is available on this platform.")


def system_voices() -> list[dict]:
    if sys.platform == "win32":
        proc = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SAPI_SCRIPT),
                               # "-" as a value makes Windows PowerShell exit 2 without output; any placeholder works
                               "-TextFile", "unused", "-Out", "unused", "-ListVoices"], capture_output=True, text=True,
                              timeout=60, creationflags=_NO_WINDOW)
        if proc.returncode != 0:
            return []
        raw = json.loads(proc.stdout.strip() or "[]")
        return [{"id": v["name"], "name": v["name"].replace("Microsoft ", "").replace(" Desktop", ""),
                 "locale": v["culture"], "gender": v["gender"]} for v in raw]
    if sys.platform == "darwin":
        proc = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=30)
        out = []
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].replace("_", "-").startswith("en"):
                out.append({"id": parts[0], "name": parts[0], "locale": parts[1].replace("_", "-"), "gender": ""})
        return out
    return []


_edge_cache: dict = {"at": 0.0, "voices": None}


def edge_voices() -> tuple[list[dict], bool]:
    """(voices, online). English US, Canadian and British voices; the built-in list when offline."""
    if _edge_cache["voices"] and time.time() - _edge_cache["at"] < 86400:
        return _edge_cache["voices"], True
    try:
        import asyncio

        import edge_tts
        raw = asyncio.run(asyncio.wait_for(edge_tts.list_voices(), timeout=10))
        voices = [{"id": v["ShortName"], "name": v.get("FriendlyName", v["ShortName"]).split(" - ")[0]
                   .replace("Microsoft ", "").replace(" Online (Natural)", ""),
                   "locale": v["Locale"], "gender": v.get("Gender", "")}
                  for v in raw if v["Locale"] in EDGE_LOCALES]
        _edge_cache.update(at=time.time(), voices=voices)
        return voices, True
    except Exception:  # noqa: BLE001 - offline or blocked
        return EDGE_FALLBACK, False

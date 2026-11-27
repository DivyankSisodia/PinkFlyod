"""Voice takes: one audio file plus word timings per narration line, stored under data/takes/.

A generated take is keyed by a hash of (engine, voice, rate, text), so asking again for an unchanged line returns
the stored take instantly and only edited lines are re-voiced. Recorded and imported takes are keyed by their bytes.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from .. import providers
from ..config import Settings
from ..db import now_iso
from ..render.ffmpeg import CancelToken, probe_json, run
from ..timeline.words import Word, anchored_timings, normalize_text, text_sha256, to_lists, tokenize, transfer_timings
from . import engines

TAKE_VERSION = 2          # 2: Windows voice timings fixed (SAPI word positions assume 16 kHz audio)
RATE = 48000


class TakeError(Exception):
    pass


def _key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join([str(TAKE_VERSION), *parts]).encode("utf-8")).hexdigest()


def _paths(settings: Settings, key: str) -> tuple[Path, Path]:
    d = settings.takes_dir / key[:2]
    return d / f"{key}.wav", d / f"{key}.json"


def take_file(settings: Settings, name: str) -> Path | None:
    """The WAV for a take file name like ``<key>.wav`` (only names this module creates)."""
    key = name.removesuffix(".wav")
    if len(key) != 64 or any(ch not in "0123456789abcdef" for ch in key):
        return None
    wav, _ = _paths(settings, key)
    return wav if wav.is_file() else None


def _silences(path: Path) -> list[tuple[float, float]]:
    import re
    err = run(["-i", str(path), "-af", "silencedetect=noise=-38dB:d=0.12", "-f", "null", "-"],
              label="find pauses", loglevel="info")
    out, start = [], None
    for m in re.finditer(r"silence_(start|end): (-?[\d.]+)", err):
        t = max(0.0, float(m.group(2)))
        if m.group(1) == "start":
            start = t
        elif start is not None:
            out.append((start, t))
            start = None
    if start is not None:
        out.append((start, _duration(path)))
    return out


def _duration(path: Path) -> float:
    info = probe_json(path)
    return float(info["format"]["duration"])


def _to_wav(src: Path, dest: Path, cancel: CancelToken | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=dest.parent, suffix=".wav")
    os.close(fd)
    tmp = Path(name)
    try:
        run(["-i", str(src), "-vn", "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", str(tmp)], label="voice audio",
            cancel=cancel, timeout=600)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def _record(settings: Settings, key: str, wav: Path, text: str, words: list[Word], timing: str, *, method: str,
            provider: str | None, voice_id: str | None, rate_pct: int | None, model_id: str | None = None) -> dict:
    take = {
        "id": "tk_" + key[:32],
        "method": method,
        "provider": provider,
        "voice_id": voice_id,
        "rate_pct": rate_pct,
        "text_sha256": text_sha256(text),
        "audio_path": settings.to_project_path(wav),
        "duration_s": round(_duration(wav), 3),
        "words": to_lists(words),
        "timing": timing,
        "created_at": now_iso(),
    }
    if model_id is not None:
        take["model_id"] = model_id
    _, meta = _paths(settings, key)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=meta.parent, delete=False) as output:
        temporary = Path(output.name)
        json.dump(take, output, ensure_ascii=False)
    try:
        temporary.replace(meta)
    finally:
        temporary.unlink(missing_ok=True)
    return take


def _cached(settings: Settings, key: str) -> dict | None:
    wav, meta = _paths(settings, key)
    if wav.is_file() and meta.is_file():
        return json.loads(meta.read_text(encoding="utf-8"))
    return None


def generate(settings: Settings, text: str, provider: str, voice_id: str, rate_pct: int = 0,
             cancel: CancelToken | None = None, *, model_id: str | None = None, config: dict | None = None,
             on_audio: Callable[[], None] | None = None) -> dict:
    """A take for ``text`` in this voice (from the store when it was made before)."""
    text = normalize_text(text)
    if not text:
        raise TakeError("There is no text to speak.")
    if provider not in ("edge", "system", "elevenlabs"):
        raise TakeError("Choose a narration provider first.")
    parts = ["tts", provider, voice_id, str(rate_pct), text]
    if provider == "elevenlabs":
        config = config if config is not None else providers.ProviderSettings(settings).read()
        if not model_id or not voice_id:
            raise TakeError("Select a speaker and an ElevenLabs model before generating narration.")
        if not -30 <= rate_pct <= 20:
            raise TakeError("ElevenLabs pace must be between −30% and +20%.")
        parts.append(model_id)
    key = _key(*parts)
    hit = _cached(settings, key)
    if hit:
        return hit
    wav, _ = _paths(settings, key)
    with tempfile.TemporaryDirectory(dir=settings.scratch_dir) as tmpd:
        work = Path(tmpd)
        if provider == "edge":
            audio, native, used_voice = engines.edge(text, voice_id, rate_pct, work)
        elif provider == "elevenlabs":
            audio, native, used_voice = providers.speech(config, text, voice_id, model_id, rate_pct, work)
        else:
            audio, native, used_voice = engines.system(text, voice_id, rate_pct, work)
        if cancel is not None:
            cancel.check("voice")
        if on_audio is not None:
            on_audio()
        _to_wav(audio, wav, cancel)
    tokens = tokenize(text)
    dur = _duration(wav)
    if native:
        words, timing = transfer_timings(tokens, native, dur), "native"
    else:
        words, pinned = anchored_timings(tokens, dur, _silences(wav))
        timing = "estimated"
    # The requested voice id is recorded (an empty id means "the default voice"), so staleness compares like with like.
    del used_voice
    return _record(settings, key, wav, text, words, timing, method="tts", provider=provider, voice_id=voice_id,
                   rate_pct=rate_pct, model_id=model_id if provider == "elevenlabs" else None)


def from_audio(settings: Settings, src: Path, text: str, method: str) -> dict:
    """A recorded or imported take. Word times are pinned to the pauses in the audio, estimated in between."""
    if method not in ("recorded", "imported"):
        raise TakeError("Unknown take method.")
    text = normalize_text(text)
    if not text:
        raise TakeError("Type the line first, so captions know the words.")
    digest = hashlib.sha256()
    with src.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    key = _key(method, digest.hexdigest(), text)
    hit = _cached(settings, key)
    if hit:
        return hit
    wav, _ = _paths(settings, key)
    _to_wav(src, wav)
    dur = _duration(wav)
    if dur < 0.2:
        wav.unlink(missing_ok=True)
        raise TakeError("That recording is too short.")
    words, _pinned = anchored_timings(tokenize(text), dur, _silences(wav))
    return _record(settings, key, wav, text, words, "estimated", method=method, provider=None, voice_id=None,
                   rate_pct=None)

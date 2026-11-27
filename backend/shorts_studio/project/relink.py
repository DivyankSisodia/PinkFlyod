"""Find moved or replaced media, and check a file the user picks to relink it."""
from __future__ import annotations

import os
from pathlib import Path

from ..config import Settings
from ..media.probe import ProbeError, probe_file, sample_sha256

MAX_SEARCH_FILES = 50_000
MAX_SEARCH_DEPTH = 8


def source_status(settings: Settings, source: dict) -> str:
    """ok | missing | changed. ``changed`` = a file is at the path but it is not the one imported."""
    path = settings.resolve_media_path(source["path"])
    fp = source["fingerprint"]
    try:
        st = os.stat(path)
    except OSError:
        return "missing"
    if not path.is_file():
        return "missing"
    if st.st_size == fp["size_bytes"] and abs(st.st_mtime - fp["mtime"]) < 0.01:
        return "ok"
    if st.st_size != fp["size_bytes"]:
        return "changed"
    try:
        return "ok" if sample_sha256(path) == fp["sample_sha256"] else "changed"
    except OSError:
        return "missing"


def check_sources(settings: Settings, doc: dict) -> dict[str, str]:
    return {sid: source_status(settings, s) for sid, s in doc["sources"].items()}


def used_source_ids(doc: dict) -> set[str]:
    """Sources an enabled scene (or the music track) actually uses."""
    used: set[str] = set()
    for scene in doc["scenes"]:
        if not scene["enabled"]:
            continue
        for slot in ("primary", "secondary"):
            layer = scene["layers"].get(slot)
            if layer is None or (slot == "secondary" and scene["layout"]["type"] == "full"):
                continue
            if layer["type"] == "segment":
                seg = doc["segments"].get(layer["segment_id"])
                if seg:
                    used.add(seg["source_id"])
            elif layer["type"] == "image":
                used.add(layer["source_id"])
        for sfx in scene["sfx"]:
            if sfx["sound"].startswith("src_"):
                used.add(sfx["sound"])
    music = doc["audio"]["music"]
    if music and music["enabled"]:
        used.add(music["source_id"])
    return used


def compare(expected: dict, actual: dict) -> dict:
    """How a candidate file compares with the fingerprint the project remembers."""
    identical = expected["sample_sha256"] == actual["sample_sha256"] and expected["size_bytes"] == actual["size_bytes"]
    reasons = []
    exp_d, act_d = expected.get("duration_s"), actual.get("duration_s")
    if (exp_d is None) != (act_d is None) or (exp_d is not None and abs(exp_d - act_d) > max(0.1, exp_d * 0.01)):
        reasons.append(f"length is {act_d or 0:.2f}s, expected {exp_d or 0:.2f}s")
    if (expected.get("width"), expected.get("height")) != (actual.get("width"), actual.get("height")):
        reasons.append(f"size is {actual.get('width')}×{actual.get('height')}, "
                       f"expected {expected.get('width')}×{expected.get('height')}")
    if expected.get("has_audio") != actual.get("has_audio"):
        reasons.append("it has sound" if actual.get("has_audio") else "it has no sound")
    return {"identical": identical, "compatible": not reasons, "reasons": reasons}


def check_candidate(path: Path, source: dict) -> dict:
    """Probe ``path`` as a replacement for ``source``. Trims stay valid only if it's compatible."""
    try:
        kind, fp, extra = probe_file(path)
    except ProbeError as e:
        return {"ok": False, "error": str(e)}
    if kind != source["kind"]:
        return {"ok": False, "error": f"That file is a {kind}; this source is a {source['kind']}."}
    return {"ok": True, "kind": kind, "fingerprint": fp, "extra": extra, **compare(source["fingerprint"], fp)}


def search_folder(folder: Path, sources: dict[str, dict]) -> dict[str, str]:
    """Look under ``folder`` for files with the same name (then the same size) as each missing source.

    Only files whose sample hash matches are returned, so a relink found this way is always identical."""
    wanted_names: dict[str, list[str]] = {}
    for sid, s in sources.items():
        name = Path(s["display_name"]).name.lower()
        orig = Path(s["path"].replace("data:", "", 1)).name.lower()
        for n in {name, orig}:
            wanted_names.setdefault(n, []).append(sid)
    by_size: dict[int, list[str]] = {}
    for sid, s in sources.items():
        by_size.setdefault(s["fingerprint"]["size_bytes"], []).append(sid)

    found: dict[str, str] = {}
    seen = 0
    base_depth = len(folder.resolve().parts)
    for dirpath, dirnames, filenames in os.walk(folder):
        if len(Path(dirpath).parts) - base_depth >= MAX_SEARCH_DEPTH:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            seen += 1
            if seen > MAX_SEARCH_FILES or len(found) == len(sources):
                return found
            candidates = list(wanted_names.get(fn.lower(), []))
            full = Path(dirpath) / fn
            if not candidates:
                try:
                    candidates = by_size.get(full.stat().st_size, [])
                except OSError:
                    continue
            for sid in candidates:
                if sid in found:
                    continue
                s = sources[sid]
                try:
                    if full.stat().st_size == s["fingerprint"]["size_bytes"] and \
                            sample_sha256(full) == s["fingerprint"]["sample_sha256"]:
                        found[sid] = str(full)
                except OSError:
                    continue
    return found

"""Your gameplay library: clips copied into data/gameplay/, tagged, and picked from without repeating stretches."""
from __future__ import annotations

import random
import shutil
from pathlib import Path

from ..config import Settings
from ..db import Database
from ..ids import new_id
from ..jobs import JobManager
from ..project import defaults as d
from . import importer, samples
from .probe import VIDEO_SUFFIXES, ProbeError, probe_file


class GameplayError(Exception):
    pass


def add(settings: Settings, db: Database, jobs: JobManager, paths: list[str], tags: list[str] | None = None,
        *, sample: bool = False, downloaded: bool = False, display_name: str | None = None) -> tuple[list[dict], list[dict]]:
    added, errors = [], []
    for raw in paths:
        src = Path(raw)
        if src.suffix.lower() not in VIDEO_SUFFIXES:
            errors.append({"path": raw, "error": f"{src.name}: gameplay must be a video file."})
            continue
        if not src.is_file():
            errors.append({"path": raw, "error": f"{src.name} wasn't found."})
            continue
        clip_id = new_id("gpc")
        folder = settings.gameplay_dir / clip_id
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / src.name
        try:
            if src.resolve() != dest.resolve():
                shutil.copy2(src, dest)
        except OSError as e:
            shutil.rmtree(folder, ignore_errors=True)
            errors.append({"path": raw, "error": f"{src.name} couldn't be copied: {e.strerror or e}"})
            continue
        try:
            kind, fp, extra = probe_file(dest)
        except ProbeError as e:
            shutil.rmtree(folder, ignore_errors=True)
            errors.append({"path": raw, "error": str(e)})
            continue
        if kind != "video":
            shutil.rmtree(folder, ignore_errors=True)
            errors.append({"path": raw, "error": f"{src.name} is not a video."})
            continue
        clean_tags = sorted({t.strip().lower()[:30] for t in (tags or []) if t.strip()})
        db.insert_clip(clip_id, dest, (display_name or src.stem)[:80], clean_tags, fp, sample, downloaded)
        record = d.source_record("video", settings.to_project_path(dest), dest.name, fp, origin="gameplay_library")
        importer.register(settings, db, jobs, clip_id, record, extra)     # posters and filmstrips for the library
        added.append(db.get_clip(clip_id))
    return added, errors


def add_sample(settings: Settings, db: Database, jobs: JobManager, cancel=None) -> dict:
    tmp = settings.scratch_dir / samples.GAMEPLAY_NAME
    samples.gameplay_clip(tmp, cancel=cancel)
    added, errors = add(settings, db, jobs, [str(tmp)], ["sample", "generated"], sample=True)
    tmp.unlink(missing_ok=True)
    if errors:
        raise GameplayError(errors[0]["error"])
    return added[0]


def remove(settings: Settings, db: Database, clip_id: str) -> None:
    clip = db.get_clip(clip_id)
    if clip is None:
        raise GameplayError("That clip isn't in the library.")
    db.delete_clip(clip_id)
    shutil.rmtree(settings.gameplay_dir / clip_id, ignore_errors=True)


def free_gaps(duration: float, used: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Stretches of the clip no earlier pick has used."""
    gaps, t = [], 0.0
    for a, b in sorted(used):
        if a > t:
            gaps.append((t, min(a, duration)))
        t = max(t, b)
    if t < duration:
        gaps.append((t, duration))
    return [(a, b) for a, b in gaps if b > a]


def choose_start(duration: float, need: float, used: list[tuple[float, float]], rng: random.Random) -> float:
    """A random start for a ``need``-second stretch. If any unused stretch is long enough, the pick lies inside one
    (so it never repeats footage); otherwise it overlaps earlier picks as little as possible."""
    latest = duration - need
    if latest <= 0:
        return 0.0
    fits = [(a, b) for a, b in free_gaps(duration, used) if b - a >= need - 1e-9]
    if fits:
        weights = [b - a - need + 1e-3 for a, b in fits]
        a, b = rng.choices(fits, weights=weights)[0]
        return round(rng.uniform(a, b - need), 3) if b - need > a else round(a, 3)

    def overlap(a: float) -> float:
        b = a + need
        return sum(max(0.0, min(b, u1) - max(a, u0)) for u0, u1 in used)

    candidates = [rng.uniform(0, latest) for _ in range(64)]
    # Also try the gaps between earlier picks, so a nearly-full clip still finds its free stretches.
    for u0, u1 in used:
        for a in (u1, u0 - need):
            if 0 <= a <= latest:
                candidates.append(a)
    best = min(candidates, key=lambda a: (round(overlap(a), 3), rng.random()))
    return round(best, 3)


def pick(settings: Settings, db: Database, clip_id: str, seconds: float, *, project_id: str | None,
         scene_id: str | None, seed: int | None = None) -> dict:
    """A random stretch of ``seconds`` that doesn't repeat earlier picks; returns a source and a segment to add."""
    clip = db.get_clip(clip_id)
    if clip is None or not clip["exists"]:
        raise GameplayError("That gameplay clip is missing from the library.")
    duration = float(clip["fingerprint"]["duration_s"] or 0)
    seed = random.SystemRandom().randrange(1, 2 ** 31) if seed is None else int(seed)
    used = [(u["in_s"], u["out_s"]) for u in db.usage(clip_id)]
    need = min(seconds, duration)
    start = choose_start(duration, need, used, random.Random(seed))
    end = round(min(duration, start + need), 3)
    db.add_usage(clip_id, start, end, project_id, scene_id)
    source_id = new_id("src")
    record = d.source_record("video", settings.to_project_path(Path(clip["path"])), Path(clip["path"]).name,
                             clip["fingerprint"], origin="gameplay_library",
                             ownership="third_party" if clip["downloaded"] else "own")
    record["gameplay_clip_id"] = clip_id
    segment = d.segment(source_id, start, end, clip["display_name"][:80], "gameplay_pick")
    segment["pick"] = {"strategy": "random_nonrepeating", "seed": seed, "picked_at": d.now_iso()}
    return {"source_id": source_id, "source": record, "segment_id": new_id("seg"), "segment": segment,
            "loop_needed": duration + 1e-6 < seconds, "overlap_s": round(sum(
                max(0.0, min(end, u1) - max(start, u0)) for u0, u1 in used), 3)}

"""Rules JSON Schema cannot express (docs/phase-0/04-project-schema.md §3, rules 1–6).

Pure functions over a structurally valid document. Rules that need resolved timing (length caps, cue ranges)
live in timeline/resolve.py; rules that need the file system (missing media) live in project/relink.py.
"""
from __future__ import annotations

from .issues import Issue

_EPS = 1e-6


def semantic_issues(doc: dict) -> list[Issue]:
    issues: list[Issue] = []
    sources = doc["sources"]
    segments = doc["segments"]
    fps = doc["output"]["fps"]

    for seg_id, seg in segments.items():
        where = f"/segments/{seg_id}"
        src = sources.get(seg["source_id"])
        if src is None:
            issues.append(Issue("missing_reference", f"Segment {seg_id} points at a source that is not in the project.",
                                path=where))
            continue
        if src["kind"] not in ("video", "audio"):
            issues.append(Issue("wrong_kind", f"Segment {seg_id} trims a {src['kind']}; only video or audio can be trimmed.",
                                path=where))
        if seg["out_s"] - seg["in_s"] < 1 / fps - _EPS:
            issues.append(Issue("empty_segment", f"Segment {seg_id} is shorter than one frame.", path=where))
        dur = src["fingerprint"].get("duration_s")
        if dur is not None and seg["out_s"] > dur + 0.05:
            issues.append(Issue("segment_past_end",
                                f"Segment {seg_id} ends at {seg['out_s']:.2f}s but the source is {dur:.2f}s long.",
                                path=where))

    seen: set[str] = set()
    for i, scene in enumerate(doc["scenes"]):
        where = f"/scenes/{i}"
        sid = scene["id"]
        if sid in seen:
            issues.append(Issue("duplicate_id", f"Two scenes share the id {sid}.", path=where, scene_id=sid))
        seen.add(sid)
        layers = scene["layers"]
        for slot in ("primary", "secondary"):
            layer = layers.get(slot)
            if layer is not None:
                issues.extend(_layer_issues(layer, sources, segments, f"{where}/layers/{slot}", sid))
        if scene["layout"]["type"] in ("split", "pip") and layers.get("secondary") is None:
            issues.append(Issue("layout_needs_secondary",
                                f"Scene “{scene['name']}” uses a {scene['layout']['type']} layout but has no second layer.",
                                path=f"{where}/layout", scene_id=sid))
        driver = scene["duration"]["driver"]
        if driver == "primary" and layers["primary"]["type"] != "segment":
            issues.append(Issue("driver_needs_segment",
                                f"Scene “{scene['name']}” takes its length from its clip, but its main layer is not a clip.",
                                path=f"{where}/duration", scene_id=sid))
        if driver == "narration" and not ((scene.get("narration") or {}).get("text") or "").strip():
            issues.append(Issue("driver_needs_narration",
                                f"Scene “{scene['name']}” takes its length from narration, but has no narration text.",
                                path=f"{where}/duration", scene_id=sid))
        for k, cue in enumerate(scene["captions"]["manual_cues"]):
            if cue["end_s"] <= cue["start_s"]:
                issues.append(Issue("bad_cue", "A caption cue ends before it starts.",
                                    path=f"{where}/captions/manual_cues/{k}", scene_id=sid))
        for k, sfx in enumerate(scene["sfx"]):
            if sfx["sound"].startswith("src_") and sfx["sound"] not in sources:
                issues.append(Issue("missing_reference", "A sound effect points at a source that is not in the project.",
                                    path=f"{where}/sfx/{k}", scene_id=sid))

    music = doc["audio"]["music"]
    if music is not None:
        src = sources.get(music["source_id"])
        if src is None:
            issues.append(Issue("missing_reference", "The music track is not in the project.", path="/audio/music"))
        elif not src["fingerprint"]["has_audio"]:
            issues.append(Issue("wrong_kind", "The music track has no sound.", path="/audio/music"))
    return issues


def _layer_issues(layer: dict, sources: dict, segments: dict, where: str, sid: str) -> list[Issue]:
    out: list[Issue] = []
    kind = layer["type"]
    if kind == "segment":
        seg = segments.get(layer["segment_id"])
        if seg is None:
            out.append(Issue("missing_reference", "A layer points at a clip selection that is not in the project.",
                             path=where, scene_id=sid))
        elif sources.get(seg["source_id"], {}).get("kind") != "video":
            out.append(Issue("wrong_kind", "A picture layer must use a video clip.", path=where, scene_id=sid))
    elif kind == "image":
        src = sources.get(layer["source_id"])
        if src is None:
            out.append(Issue("missing_reference", "A layer points at an image that is not in the project.",
                             path=where, scene_id=sid))
        elif src["kind"] != "image":
            out.append(Issue("wrong_kind", "An image layer must use an image file.", path=where, scene_id=sid))
    return out

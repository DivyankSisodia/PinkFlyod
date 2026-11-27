"""resolve(document) -> timeline. Pure: no file system, no clock, no FFmpeg.

The browser preview draws from this timeline and render/plan.py turns the same timeline into FFmpeg commands, so the
two cannot disagree about scene timing, layout rectangles, crop windows, captions, overlays or which sound plays when.

Scene durations are quantised to whole frames once, here; everything downstream uses frame counts. Scene content is
described in scene-local time so an unchanged scene renders to the same cached segment wherever it sits.
"""
from __future__ import annotations

import math

from ..media.probe import display_size
from ..render.raster import raster_id
from ..schema.issues import Issue
from ..schema.semantic import semantic_issues
from . import envelope as env
from .geometry import even, place
from .words import Word, caption_chunks, from_lists, normalize_text, text_sha256, tokenize

RESOLVER_VERSION = 2
SHORTS_MAX_S = 180.0
SHORTS_LONG_WARN_S = 60.0
WORDS_PER_SECOND = 2.7
KEN_BURNS_ZOOM = 1.15
MUSIC_GATE_RAMP_S = 0.25
LATER = "This build doesn't render it yet"
PIP_ASPECTS = {"9:16": 16 / 9, "1:1": 1.0, "4:3": 3 / 4, "16:9": 9 / 16}


def _frames(seconds: float, fps: int) -> int:
    return max(1, math.floor(seconds * fps + 0.5))


def safe_rect(output: dict) -> dict:
    sa = output["safe_area"]
    ref_w, ref_h = sa["reference_px"]
    kx, ky = output["width"] / ref_w, output["height"] / ref_h
    ins = sa["insets_px"]
    x, y = round(ins["left"] * kx), round(ins["top"] * ky)
    return {"x": x, "y": y, "w": output["width"] - x - round(ins["right"] * kx),
            "h": output["height"] - y - round(ins["bottom"] * ky)}


def needs_rights(doc: dict, used: set[str]) -> bool:
    for sid in used:
        s = doc["sources"].get(sid)
        if s and (s["origin"] == "url_download" or s["ownership"] in ("third_party", "unknown")):
            return True
    return False


def effective_voice(doc: dict, scene: dict) -> dict:
    n = scene.get("narration") or {}
    return n.get("voice") or doc["voice"]


def take_state(doc: dict, scene: dict) -> str:
    """none | ready | stale. A take is stale when the line or (for generated takes) the voice has changed."""
    n = scene.get("narration")
    if not n or not normalize_text(n["text"]):
        return "none"
    take = n.get("take")
    if not take:
        return "missing"
    if take["text_sha256"] != text_sha256(n["text"]):
        return "stale"
    if take["method"] == "tts":
        v = effective_voice(doc, scene)
        if (take["provider"], take["voice_id"], take["rate_pct"] or 0) != (v["provider"], v["voice_id"], v["rate_pct"]):
            return "stale"
        if v["provider"] == "elevenlabs" and take.get("model_id") != v.get("model_id"):
            return "stale"
    return "ready"


def ranks(doc: dict) -> dict[str, int]:
    r = doc["ranking"]
    if not r["enabled"]:
        return {}
    entries = [s["id"] for s in doc["scenes"] if s["enabled"] and s["rank"]["include"]]
    n = len(entries)
    return {sid: (n - i if r["direction"] == "descending" else i + 1) for i, sid in enumerate(entries)}


class _Ctx:
    def __init__(self, doc: dict):
        self.doc = doc
        out = doc["output"]
        self.W, self.H, self.fps = out["width"], out["height"], out["fps"]
        self.safe = safe_rect(out)
        self.issues: list[Issue] = []
        self.unsupported: dict[str, list[str]] = {}
        self.rasters: dict[str, dict] = {}
        self.used: set[str] = set()
        self.cursors: dict[str, float] = {}     # segment id -> source seconds already played (continue_from_previous)

    def raster(self, spec: dict) -> str:
        spec = {"frame": [self.W, self.H], "safe": self.safe, **spec}
        rid = raster_id(spec)
        self.rasters[rid] = spec
        return rid

    def later(self, feature: str, scene_id: str | None = None) -> None:
        self.unsupported.setdefault(feature, [])
        if scene_id:
            self.unsupported[feature].append(scene_id)


def resolve(doc: dict, statuses: dict[str, str] | None = None) -> dict:
    """``statuses`` maps source id -> ok | missing | changed (from project/relink.check_sources)."""
    c = _Ctx(doc)
    c.issues.extend(semantic_issues(doc))
    out = doc["output"]
    fps = c.fps
    rank_of = ranks(doc)
    title_bar = doc["overlays"]["title_bar"]
    title_h = _title_bar_height(title_bar) if title_bar else 0
    top_offset = title_h if title_bar and title_bar["position"] == "top" else 0
    if out["video"]["encoder"] != "libx264":
        c.later(f"Encoder {out['video']['encoder']} (libx264 is used instead)")

    scenes_out: list[dict] = []
    start_frame = 0
    third_party_frames = 0
    enabled = [s for s in doc["scenes"] if s["enabled"]]
    for index, scene in enumerate(doc["scenes"]):
        if not scene["enabled"]:
            continue
        sid = scene["id"]
        if scene["transition_in"]["type"] != "cut":
            c.later("Transitions other than a cut", sid)
        state = take_state(doc, scene)
        words = _take_words(scene) if state in ("ready", "stale") else []
        frames, estimated = _scene_frames(doc, scene, fps, state)
        dur = frames / fps
        if estimated:
            c.issues.append(Issue("duration_estimated", f"Scene “{scene['name']}” has no voice yet, so its length is "
                                  "estimated from the words.", "warning", scene_id=sid))
        _narration_issues(c, scene, state)
        layout = _layout(c, scene)
        layers, audio = [], []
        for slot, rect in layout["draw"]:
            layer_doc = scene["layers"][slot]
            layer = _layer(c, scene, slot, layer_doc, rect, dur)
            if layer is None:
                continue
            if layout["type"] == "pip" and slot == layout["pip"]["inset_layer"]:
                layer["pip"] = layout["pip"]
            layers.append(layer)
            if layer.get("source_id"):
                c.used.add(layer["source_id"])
                src = doc["sources"][layer["source_id"]]
                if src["ownership"] in ("third_party", "unknown") or src["origin"] == "url_download":
                    third_party_frames += frames if slot == "primary" else 0
            ev = _source_audio(c, scene, slot, layer, words, dur)
            if ev:
                audio.append(ev)
        narration = None
        if state in ("ready", "stale"):
            n = scene["narration"]
            take = n["take"]
            narration = {"take_id": take["id"], "audio_path": take["audio_path"], "start_s": n["offset_s"],
                         "duration_s": take["duration_s"], "state": state,
                         "words": [[w.text, round(w.start, 3), round(w.end, 3)] for w in words]}
            if scene["audio"]["narration"]["enabled"]:
                audio.append({"track": "narration", "path": take["audio_path"], "start_s": n["offset_s"],
                              "source_in_s": 0.0, "read_s": min(take["duration_s"], max(0.0, dur - n["offset_s"])),
                              "speed": 1.0, "gain_db": scene["audio"]["narration"]["gain_db"], "duck": None,
                              "copies": None, "fade_s": 0.0})
        overlays = _scene_overlays(c, scene, rank_of.get(sid), words, dur, top_offset, enabled, rank_of)
        sfx = [{"sound": s["sound"], "at_s": round(min(s["at_s"], dur), 4), "gain_db": s["gain_db"]}
               for s in scene["sfx"]]
        for s in scene["sfx"]:
            if s["sound"].startswith("src_"):
                c.used.add(s["sound"])
        scenes_out.append({
            "id": sid, "index": index, "name": scene["name"], "rank": rank_of.get(sid),
            "start_frame": start_frame, "frames": frames,
            "start_s": round(start_frame / fps, 6), "duration_s": round(dur, 6),
            "background_color": scene["layout"]["background_color"],
            "layout": {k: v for k, v in layout.items() if k != "draw"},
            "layers": layers, "overlays": overlays, "audio": audio, "narration": narration, "sfx": sfx,
            "music_on": bool(scene["audio"]["music"]["enabled"]), "edge_fade_s": doc["audio"]["edge_fade_ms"] / 1000,
        })
        start_frame += frames

    total_frames = start_frame
    total_s = total_frames / fps
    project_overlays = _project_overlays(c, title_bar, title_h, total_s)
    music = _music(c, scenes_out, total_s)
    _limits(c, out, total_s, scenes_out)
    _media_and_rights(c, statuses or {}, total_frames, third_party_frames)
    for feature, ids in c.unsupported.items():
        c.issues.append(Issue("not_in_this_build", f"{feature}: {LATER}.", "warning",
                              scene_id=ids[0] if len(ids) == 1 else None))
    audible = music is not None or any(s["audio"] or s["sfx"] for s in scenes_out)
    blank = c.raster({"kind": "blank"})
    return {
        "blank_raster": blank,
        "resolver_version": RESOLVER_VERSION,
        "output": {"width": c.W, "height": c.H, "fps": fps},
        "frames": total_frames,
        "duration_s": round(total_s, 6),
        "safe_area": c.safe,
        "audible": audible,
        "scenes": scenes_out,
        "overlays": project_overlays,
        "music": music,
        "rasters": c.rasters,
        "sources": _source_summary(doc, statuses or {}),
        "needs_rights": needs_rights(doc, c.used),
        "issues": [i.to_dict() for i in c.issues],
    }


# ── timing ───────────────────────────────────────────────────────────────
def _take_words(scene: dict) -> list[Word]:
    n = scene["narration"]
    words = from_lists(n["take"]["words"])
    edits = {e["index"]: e["text"] for e in scene["captions"]["word_edits"]}
    off = n["offset_s"]
    return [Word(edits.get(i, w.text), w.start + off, w.end + off) for i, w in enumerate(words)]


def _scene_frames(doc: dict, scene: dict, fps: int, state: str) -> tuple[int, bool]:
    dur_cfg = scene["duration"]
    primary = scene["layers"]["primary"]
    driver = dur_cfg["driver"]
    if driver == "fixed" and dur_cfg["fixed_s"]:
        return _frames(dur_cfg["fixed_s"], fps), False
    if driver == "narration" and scene.get("narration"):
        n = scene["narration"]
        if state in ("ready", "stale"):
            return _frames(n["offset_s"] + n["take"]["duration_s"] + dur_cfg["tail_pad_s"], fps), False
        words = len(tokenize(n["text"]))
        return _frames(n["offset_s"] + max(1.0, words / WORDS_PER_SECOND) + dur_cfg["tail_pad_s"], fps), True
    if primary["type"] == "segment":
        seg = doc["segments"].get(primary["segment_id"])
        if seg:
            return _frames((seg["out_s"] - seg["in_s"]) / primary["playback"]["speed"], fps), False
    return _frames(3.0, fps), False


def _narration_issues(c: _Ctx, scene: dict, state: str) -> None:
    n = scene.get("narration")
    if not n or state == "none":
        return
    uses_words = _caption_mode(c.doc, scene) == "narration_words"
    if not (scene["audio"]["narration"]["enabled"] or uses_words):
        return
    if state == "missing":
        c.issues.append(Issue("voice_missing", f"Scene “{scene['name']}” has narration text but no voice yet. "
                              "Generate, record or import it.", scene_id=scene["id"]))
    elif state == "stale":
        c.issues.append(Issue("voice_stale", f"Scene “{scene['name']}”: the line changed since its voice was made. "
                              "Regenerate it (only this scene's voice is redone).", scene_id=scene["id"]))


# ── layout and layers ────────────────────────────────────────────────────
def _layout(c: _Ctx, scene: dict) -> dict:
    lay = scene["layout"]
    W, H = c.W, c.H
    full = {"x": 0, "y": 0, "w": W, "h": H}
    has_secondary = scene["layers"]["secondary"] is not None
    if lay["type"] == "split" and has_secondary:
        sp = lay["split"]
        gap = sp["gap_px"]
        top_h = max(2, even(H * sp["divider"] - gap / 2))
        bot_y = min(H - 2, even(H * sp["divider"] + gap / 2))
        top = {"x": 0, "y": 0, "w": W, "h": top_h}
        bottom = {"x": 0, "y": bot_y, "w": W, "h": H - bot_y}
        prim, sec = (top, bottom) if sp["primary_position"] == "top" else (bottom, top)
        gap_rect = {"x": 0, "y": top_h, "w": W, "h": bot_y - top_h, "color": sp["gap_color"]} if bot_y > top_h else None
        return {"type": "split", "slots": {"primary": prim, "secondary": sec}, "gap": gap_rect, "pip": None,
                "draw": [("primary", prim), ("secondary", sec)]}
    if lay["type"] == "pip" and has_secondary:
        p = lay["pip"]
        inset = p["inset_layer"]
        base = "secondary" if inset == "primary" else "primary"
        w = max(32, even(W * p["width"]))
        ratio = PIP_ASPECTS.get(p["aspect"])
        if ratio is None:
            ratio = _layer_ratio(c.doc, scene["layers"][inset]) or 9 / 16
        h = max(32, min(even(H * 0.9), even(w * ratio)))
        rect = {"x": even(p["x"] * (W - w)), "y": even(p["y"] * (H - h)), "w": w, "h": h}
        radius = min(p["corner_radius_px"], min(w, h) // 2)
        pip = {"inset_layer": inset, "radius": radius, "border_px": p["border_px"], "border_color": p["border_color"],
               "mask": c.raster({"kind": "pip_mask", "size": [w, h], "radius": radius}) if radius else None,
               "border": c.raster({"kind": "pip_border", "size": [w, h], "radius": radius,
                                   "border_px": p["border_px"], "color": p["border_color"]}) if p["border_px"] else None}
        return {"type": "pip", "slots": {base: full, inset: rect}, "gap": None, "pip": pip,
                "draw": [(base, full), (inset, rect)]}
    if lay["type"] in ("split", "pip"):
        c.issues.append(Issue("layout_needs_secondary", f"Scene “{scene['name']}” needs a second layer for its "
                              f"{lay['type']} layout; showing the main layer full screen.", "warning",
                              scene_id=scene["id"]))
    return {"type": "full", "slots": {"primary": full}, "gap": None, "pip": None, "draw": [("primary", full)]}


def _layer_ratio(doc: dict, layer: dict) -> float | None:
    if layer["type"] == "segment":
        seg = doc["segments"].get(layer["segment_id"])
        src = doc["sources"].get(seg["source_id"]) if seg else None
    elif layer["type"] == "image":
        src = doc["sources"].get(layer["source_id"])
    else:
        return None
    size = display_size(src["fingerprint"]) if src else None
    return size[1] / size[0] if size else None


def _layer(c: _Ctx, scene: dict, slot: str, layer: dict, rect: dict, dur: float) -> dict | None:
    rf = layer["reframe"]
    sid = scene["id"]
    base = {"slot": slot, "kind": layer["type"], "rect": rect, "mode": rf["mode"],
            "bar_color": rf.get("bar_color", "#000000"), "source_id": None, "color": None, "raster": None,
            "motion": "none", "pip": None}
    if rf.get("keyframes"):
        c.later("Moving crop (keyframes); the static crop is used", sid)
    kind = layer["type"]
    if kind == "color":
        return {**base, "color": layer["color"]}
    if kind == "text_card":
        tc = layer["text_card"]
        area = _intersect(rect, c.safe)
        area = {"x": area["x"] - rect["x"], "y": area["y"] - rect["y"], "w": area["w"], "h": area["h"]}
        rid = c.raster({"kind": "text_card", "size": [rect["w"], rect["h"]], "text_area": area, "text": tc["text"],
                        "background": tc["background"], "style": tc["style"], "align": tc["align"]})
        return {**base, "raster": rid, "color": tc["background"]}
    if kind == "image":
        src = c.doc["sources"].get(layer["source_id"])
        size = display_size(src["fingerprint"]) if src else None
        if size is None:
            return None
        motion = layer.get("motion", "none")
        if motion in ("pan_left", "pan_right"):
            c.later("Panning stills (zoom motions work)", sid)
            motion = "none"
        if motion != "none" and rf["mode"] != "fill":
            c.later("Ken Burns motion on fitted stills", sid)
            motion = "none"
        p = place(size[0], size[1], rect["w"], rect["h"], rf["mode"], rf["focus"]["x"], rf["focus"]["y"], rf["zoom"])
        return {**base, "source_id": layer["source_id"], "source_size": {"w": size[0], "h": size[1]},
                "motion": motion, "motion_zoom": KEN_BURNS_ZOOM, **p,
                "blur_background": _blur(size, rect) if rf["mode"] == "blur_fill" else None}
    seg_id = layer["segment_id"]
    seg = c.doc["segments"].get(seg_id)
    src = c.doc["sources"].get(seg["source_id"]) if seg else None
    size = display_size(src["fingerprint"]) if src else None
    if seg is None or src is None:
        return None
    if size is None:
        c.issues.append(Issue("no_picture", f"“{src['display_name']}” has no picture.", scene_id=sid))
        return None
    pb = layer["playback"]
    seg_len = max(1.0 / c.fps, seg["out_s"] - seg["in_s"])
    speed = float(pb["speed"])
    when_short = pb["when_short"]
    offset = 0.0
    if pb["continue_from_previous"]:
        offset = c.cursors.get(seg_id, 0.0)
        offset = offset % seg_len if when_short == "loop" else min(offset, seg_len - 1.0 / c.fps)
    if when_short == "slow_to_fit" and (seg_len - offset) / speed < dur:
        speed = (seg_len - offset) / dur
    need = dur * speed
    copies = None
    joins: list[float] = []
    if when_short == "loop" and need > seg_len - offset + 1e-6:
        xf = min(float(pb["loop_crossfade_s"]), seg_len / 3)
        copies = [{"in_s": round(seg["in_s"] + offset, 6), "len_s": round(seg_len - offset, 6)}]
        produced = seg_len - offset
        while produced < need - 1e-6:
            joins.append(round((produced - xf) / speed, 4))
            copies.append({"in_s": round(seg["in_s"], 6), "len_s": round(seg_len, 6)})
            produced += seg_len - xf
        read_s, pad_s = need, 0.0
        loop = {"copies": copies, "crossfade_s": round(xf, 4), "joins": joins}
    else:
        if when_short == "loop":
            when_short = "freeze_last"
        loop = None
        read_s = min(seg_len - offset, need)
        pad_s = max(0.0, dur - read_s / speed)
    c.cursors[seg_id] = offset + need          # where the next scene continues from, if it asks to
    p = place(size[0], size[1], rect["w"], rect["h"], rf["mode"], rf["focus"]["x"], rf["focus"]["y"], rf["zoom"])
    return {**base, "source_id": seg["source_id"], "segment_id": seg_id, "source_size": {"w": size[0], "h": size[1]},
            "source_in_s": round(seg["in_s"] + offset, 6), "offset_s": round(offset, 6), "segment_len_s": round(seg_len, 6),
            "read_s": round(read_s, 6), "speed": round(speed, 6), "pad_s": round(pad_s, 6),
            "when_short": when_short, "loop": loop, **p,
            "blur_background": _blur(size, rect) if rf["mode"] == "blur_fill" else None}


def _intersect(a: dict, b: dict) -> dict:
    x0, y0 = max(a["x"], b["x"]), max(a["y"], b["y"])
    x1, y1 = min(a["x"] + a["w"], b["x"] + b["w"]), min(a["y"] + a["h"], b["y"] + b["h"])
    if x1 <= x0 or y1 <= y0:
        return dict(a)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def _blur(size: tuple[int, int], rect: dict) -> dict:
    return place(size[0], size[1], rect["w"], rect["h"], "fill", 0.5, 0.5, 1.0)


# ── sound ────────────────────────────────────────────────────────────────
def _speech_spans(words: list[Word]) -> list[tuple[float, float]]:
    return env.merge_intervals([(w.start, w.end) for w in words], 0.35)


def _source_audio(c: _Ctx, scene: dict, slot: str, layer: dict, words: list[Word], dur: float) -> dict | None:
    mix = scene["audio"][slot]
    if layer["kind"] != "segment" or not mix["enabled"]:
        return None
    if not c.doc["sources"][layer["source_id"]]["fingerprint"]["has_audio"]:
        return None
    ducking = c.doc["audio"]["ducking"]
    duck = None
    if mix["duck_under_narration"] and words and scene["audio"]["narration"]["enabled"]:
        duck = env.duck(_speech_spans(words), ducking["depth_db"], ducking["attack_ms"] / 1000,
                        ducking["release_ms"] / 1000, 0.0, dur)
    loop = layer["loop"]
    return {"track": slot, "source_id": layer["source_id"], "start_s": 0.0, "source_in_s": layer["source_in_s"],
            "read_s": layer["read_s"], "speed": layer["speed"], "gain_db": mix["gain_db"], "duck": duck,
            "copies": loop["copies"] if loop else None, "crossfade_s": loop["crossfade_s"] if loop else 0.0,
            "fade_s": round(min(c.doc["audio"]["edge_fade_ms"] / 1000, dur / 4), 4)}


def _music(c: _Ctx, scenes: list[dict], total: float) -> dict | None:
    m = c.doc["audio"]["music"]
    if not m or not m["enabled"] or not scenes or not any(s["music_on"] for s in scenes):
        return None
    src = c.doc["sources"].get(m["source_id"])
    if src is None or not src["fingerprint"]["has_audio"]:
        return None
    c.used.add(m["source_id"])
    windows = [(s["start_s"], s["start_s"] + s["duration_s"], s["music_on"]) for s in scenes]
    gain = env.gate(windows, MUSIC_GATE_RAMP_S, 0.0, total)
    d = c.doc["audio"]["ducking"]
    if d["enabled"]:
        spans = []
        for s in scenes:
            n = s["narration"]
            if n and any(a["track"] == "narration" for a in s["audio"]):
                spans += [(s["start_s"] + w[1], s["start_s"] + w[2]) for w in n["words"]]
        if spans:
            gain = env.multiply(gain, env.duck(env.merge_intervals(spans, 0.35), d["depth_db"], d["attack_ms"] / 1000,
                                               d["release_ms"] / 1000, 0.0, total))
    return {"source_id": m["source_id"], "gain_db": m["gain_db"], "start_offset_s": m["start_offset_s"],
            "loop": m["loop"], "fade_in_s": m["fade_in_s"], "fade_out_s": m["fade_out_s"],
            "duration_s": src["fingerprint"]["duration_s"], "envelope": gain}


# ── overlays and captions ────────────────────────────────────────────────
def _title_bar_height(tb: dict) -> int:
    return even(tb["style"]["font_size_px"] * 1.35 + 24)


def _caption_mode(doc: dict, scene: dict) -> str:
    caps = doc["captions"]
    if not caps["enabled"]:
        return "off"
    mode = scene["captions"]["mode"]
    return caps["default_mode"] if mode == "inherit" else mode


def _scene_overlays(c: _Ctx, scene: dict, rank: int | None, words: list[Word], dur: float, top_offset: int,
                    enabled: list[dict], rank_of: dict[str, int]) -> list[dict]:
    doc = c.doc
    out: list[dict] = []
    ov = scene["overlays"]
    rk = doc["ranking"]
    label_text = (ov["label"]["text"] or scene["name"]) if ov["label"]["visible"] else None
    if rank is not None and rk["reveal"] == "list_build_up":
        rows = []
        order = [s["id"] for s in enabled if s["id"] in rank_of]
        here = order.index(scene["id"])
        for k, other_id in enumerate(order):
            other = next(s for s in enabled if s["id"] == other_id)
            o = other["overlays"]
            lab = ((o["label"]["text"] or other["name"]) if o["label"]["visible"] else "") if k <= here else ""
            rows.append({"n": rank_of[other_id], "label": lab, "current": k == here})
        rows.sort(key=lambda r: r["n"])
        rid = c.raster({"kind": "rank_list", "rows": rows, "style": rk["badge"]["style"], "top_offset": top_offset})
        out.append({"kind": "rank_list", "raster": rid, "start_s": 0.0, "end_s": dur})
    elif (rank is not None and ov["rank_badge"]["visible"]) or label_text:
        show = rank is not None and ov["rank_badge"]["visible"]
        text = rk["badge"]["format"].replace("{n}", str(rank)) if show else ""
        rid = c.raster({"kind": "badge", "text": text, "show_badge": show, "label": label_text,
                        "style": rk["badge"]["style"], "position": rk["badge"]["position"], "top_offset": top_offset})
        out.append({"kind": "badge", "raster": rid, "start_s": 0.0, "end_s": dur})
    card_end = 0.0
    card = ov["reddit_card"]
    if card:
        end = card["end_s"] if card["end_s"] is not None else _title_read_end(card["title"], words, dur)
        card_end = min(dur, end)
        author = None
        if card["author"]["mode"] == "shown" and card["author"]["name"]:
            author = card["author"]["name"]
        elif card["author"]["mode"] == "anonymized":
            author = "u/anonymous"
        rid = c.raster({"kind": "reddit_card", "community": card["community"], "title": card["title"],
                        "author": author, "show_metrics": card["show_metrics"], "metrics": card["metrics"]})
        out.append({"kind": "reddit_card", "raster": rid, "start_s": min(card["start_s"], card_end),
                    "end_s": card_end})
    for t in ov["texts"]:
        end = dur if t["end_s"] is None else min(dur, t["end_s"])
        if end > t["start_s"]:
            rid = c.raster({"kind": "text", "text": t["text"], "anchor": t["anchor"], "style": t["style"]})
            out.append({"kind": "text", "raster": rid, "start_s": t["start_s"], "end_s": end})
    out += _captions(c, scene, words, dur, card_end)
    return out


def _title_read_end(title: str, words: list[Word], dur: float) -> float:
    t = [x for x in (normalize_text(title).lower().split(" ")) if x]
    if not words or not t:
        return dur
    spoken = [w.text.lower() for w in words]
    n = len(t)
    if [w.strip(".,!?;:\"'") for w in spoken[:n]] == [w.strip(".,!?;:\"'") for w in t]:
        return min(dur, words[n - 1].end + 0.3)
    return dur


def _captions(c: _Ctx, scene: dict, words: list[Word], dur: float, hide_until: float) -> list[dict]:
    doc = c.doc
    mode = _caption_mode(doc, scene)
    caps = doc["captions"]
    style = caps["style"]
    base = {"kind": "caption", "style": style["text"], "preset": style["preset"], "anchor_y": caps["anchor_y"],
            "active_color": style["active_color"], "emphasis_color": style["emphasis_color"]}
    emph = {e.lower() for e in caps["emphasis_words"]}
    out = []
    if mode == "off":
        return out
    if mode == "source_transcript":
        c.later("Captions from the clip's own speech (transcription arrives in Phase 3)", scene["id"])
        return out
    if mode == "manual":
        for cue in scene["captions"]["manual_cues"]:
            end = min(dur, cue["end_s"])
            if end <= cue["start_s"]:
                continue
            ws = cue["text"].split()
            rid = c.raster({**base, "words": ws, "active": None, "emphasis": [_emph(w, emph) for w in ws]})
            out.append({"kind": "caption", "raster": rid, "start_s": round(cue["start_s"], 4), "end_s": round(end, 4)})
        return out
    if not words:
        return out
    spoken = [w for w in words if w.start >= hide_until - 0.05]
    for chunk in caption_chunks(spoken, style["max_words"], style["max_chars"], total=dur):
        ws = [w.text for w in chunk.words]
        flags = [_emph(w, emph) for w in ws]
        states = range(len(ws)) if style["active_color"] else [None]
        for k in states:
            start = chunk.start if k in (0, None) else chunk.words[k].start
            end = chunk.end if k is None or k + 1 >= len(ws) else chunk.words[k + 1].start
            start, end = max(0.0, start), min(dur, end)
            if end - start < 0.01:
                continue
            rid = c.raster({**base, "words": ws, "active": k, "emphasis": flags})
            out.append({"kind": "caption", "raster": rid, "start_s": round(start, 4), "end_s": round(end, 4)})
    return out


def _emph(word: str, keys: set[str]) -> bool:
    k = "".join(ch for ch in word.lower() if ch.isalnum())
    return bool(k) and (k in keys or any(ch.isdigit() for ch in k))


def _project_overlays(c: _Ctx, title_bar: dict | None, title_h: int, total: float) -> list[dict]:
    ov = c.doc["overlays"]
    out = []
    if title_bar:
        rid = c.raster({"kind": "title_bar", "text": title_bar["text"], "position": title_bar["position"],
                        "background": title_bar["background"], "style": title_bar["style"], "height": title_h})
        out.append({"kind": "title_bar", "raster": rid, "start_s": 0.0, "end_s": total})
    hook = ov["hook"]
    if hook and hook["start_s"] < total:
        rid = c.raster({"kind": "hook", "text": hook["text"], "anchor_y": hook["anchor_y"], "style": hook["style"]})
        out.append({"kind": "hook", "raster": rid, "start_s": hook["start_s"],
                    "end_s": min(total, hook["start_s"] + hook["duration_s"])})
    wm = ov["watermark"]
    if wm:
        alpha = f"{round(wm['opacity'] * 255):02X}"
        style = {"font_family": "inter", "font_size_px": 34, "color": f"#FFFFFF{alpha}", "stroke_color": "#00000000",
                 "stroke_px": 0, "box_color": None, "uppercase": False}
        rid = c.raster({"kind": "text", "text": wm["text"], "anchor": {"x": 0.5, "y": 0.97}, "style": style})
        out.append({"kind": "watermark", "raster": rid, "start_s": 0.0, "end_s": total})
    return out


# ── checks ───────────────────────────────────────────────────────────────
def _limits(c: _Ctx, out: dict, total_s: float, scenes: list[dict]) -> None:
    fps = c.fps
    if not scenes:
        c.issues.append(Issue("no_scenes", "Add at least one scene to export."))
    cap = out["max_duration_s"]
    if cap is not None and total_s > cap + 0.5 / fps:
        c.issues.append(Issue("over_cap", f"The video is {total_s:.2f}s; this project is capped at {cap:g}s. "
                              "Shorten a selection or turn the cap off in Project settings."))
    if total_s > SHORTS_MAX_S + 0.5 / fps:
        c.issues.append(Issue("over_shorts_max", f"The video is {total_s:.1f}s; YouTube Shorts can be at most 3 minutes."))
    elif total_s > SHORTS_LONG_WARN_S:
        c.issues.append(Issue("long_short", f"The video is {total_s:.1f}s. Shorts can be up to 3 minutes, but most are "
                              "under a minute.", "warning"))


def _media_and_rights(c: _Ctx, statuses: dict[str, str], total_frames: int, third_party_frames: int) -> None:
    doc = c.doc
    for src_id in sorted(c.used):
        state = statuses.get(src_id, "ok")
        if state != "ok":
            name = doc["sources"][src_id]["display_name"]
            msg = (f"“{name}” is missing. Relink it from the Media panel." if state == "missing"
                   else f"“{name}” has changed since it was imported. Relink it to confirm the file.")
            c.issues.append(Issue("media_" + state, msg, path=f"/sources/{src_id}"))
    if needs_rights(doc, c.used) and not doc["compliance"]["rights"]["confirmed"]:
        c.issues.append(Issue("rights_unconfirmed", "This project uses footage that isn't yours. Confirm you have the "
                              "rights to use it before exporting."))
    if total_frames and third_party_frames / total_frames > 0.6 and _no_added_value(doc):
        c.issues.append(Issue("reused_content", "Most of this video is someone else's footage without commentary, "
                              "narration, ranking or captions. YouTube reviews reused content like this; consider adding "
                              "your own contribution.", "warning"))


def _no_added_value(doc: dict) -> bool:
    for scene in doc["scenes"]:
        if not scene["enabled"]:
            continue
        if scene.get("narration") and scene["audio"]["narration"]["enabled"]:
            return False
        if scene["overlays"]["texts"] or scene["overlays"]["reddit_card"]:
            return False
        if doc["ranking"]["enabled"] and scene["rank"]["include"]:
            return False
        if _caption_mode(doc, scene) != "off":
            return False
    return not (doc["overlays"]["hook"] or doc["overlays"]["title_bar"])


def _source_summary(doc: dict, statuses: dict[str, str]) -> dict:
    out = {}
    for sid, s in doc["sources"].items():
        size = display_size(s["fingerprint"])
        out[sid] = {"kind": s["kind"], "display_name": s["display_name"],
                    "w": size[0] if size else None, "h": size[1] if size else None,
                    "duration_s": s["fingerprint"]["duration_s"], "has_audio": s["fingerprint"]["has_audio"],
                    "status": statuses.get(sid, "ok")}
    return out

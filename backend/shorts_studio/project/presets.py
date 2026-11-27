"""Presets create ordinary documents; they contain no render logic (docs/phase-0/04-project-schema.md §4).

After creation every field is editable and scenes from different presets can be mixed freely.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..ids import new_id
from ..timeline.words import normalize_text
from . import defaults as d


class PresetError(ValueError):
    pass


def _title_from(name: str) -> str:
    stem = Path(name).stem.replace("_", " ").replace("-", " ").strip()
    return (stem[:1].upper() + stem[1:]) if stem else "Untitled short"


def _videos(sources: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    return [(sid, s) for sid, s in sources if s["kind"] == "video"]


def _add_sources(doc: dict, sources: list[tuple[str, dict]]) -> None:
    for sid, s in sources:
        doc["sources"][sid] = s


def _segment_scene(doc: dict, sid: str, src: dict, seconds: float | None, *, ranked: bool = False,
                   created_by: str = "manual") -> dict:
    duration = float(src["fingerprint"]["duration_s"] or 0)
    out_s = duration if seconds is None else min(seconds, duration)
    if out_s * doc["output"]["fps"] < 1:
        raise PresetError(f"{src['display_name']} is shorter than one frame.")
    seg_id = new_id("seg")
    doc["segments"][seg_id] = d.segment(sid, 0.0, out_s, "Selection" if seconds else "Whole clip", created_by)
    scene = d.scene_from_segment(seg_id, _title_from(src["display_name"]), audio_on=bool(src["fingerprint"]["has_audio"]),
                                 ranked=ranked)
    doc["scenes"].append(scene)
    return scene


# ── edit an existing video ───────────────────────────────────────────────
def quick_short(sources: list[tuple[str, dict]], *, title: str | None = None, country: str = "US") -> dict:
    """One scene, the first 13 s (or less) of the first video, cover-cropped to 9:16, capped at 15 s."""
    videos = _videos(sources)
    if not videos:
        raise PresetError("Quick Short needs at least one video file.")
    first_id, first = videos[0]
    doc = d.document(title or _title_from(first["display_name"]), entry="edit_existing", preset="quick_short",
                     input_kind="files", country=country)
    doc["output"]["max_duration_s"] = d.QUICK_SHORT_CAP_S
    _add_sources(doc, sources)
    _segment_scene(doc, first_id, first, d.QUICK_SHORT_DEFAULT_S)
    return doc


def from_files(sources: list[tuple[str, dict]], *, title: str | None = None, country: str = "US",
               entry_seconds: float | None = None) -> dict:
    """One scene per video, each using the whole file (no length cap)."""
    videos = _videos(sources)
    if not videos:
        raise PresetError("Add at least one video file.")
    doc = d.document(title or _title_from(videos[0][1]["display_name"]), entry="edit_existing", preset="blank",
                     input_kind="files", country=country)
    _add_sources(doc, sources)
    for sid, s in videos:
        _segment_scene(doc, sid, s, entry_seconds, created_by="whole_source" if entry_seconds is None else "manual")
    return doc


def ranking(sources: list[tuple[str, dict]], *, title: str | None = None, country: str = "US",
            direction: str = "descending", entry_seconds: float = 6.0) -> dict:
    """One ranked entry per video (first ``entry_seconds`` of each), counting down by default.

    Ranks are never stored: they follow the scene order, so dragging an entry moves its clip, trim and label
    together and every badge renumbers itself."""
    videos = _videos(sources)
    if not videos:
        raise PresetError("A ranking needs at least one video file.")
    n = len(videos)
    doc = d.document(title or f"Top {n}", entry="edit_existing", preset="ranking", input_kind="files", country=country)
    _add_sources(doc, sources)
    doc["ranking"]["enabled"] = True
    doc["ranking"]["direction"] = direction
    doc["overlays"]["title_bar"] = d.title_bar(title or f"Top {n}")
    for sid, s in videos:
        _segment_scene(doc, sid, s, entry_seconds, ranked=True)
    return doc


def clips_over_gameplay(sources: list[tuple[str, dict]], gameplay: dict, *, title: str | None = None,
                        country: str = "US", layout: str = "split", entry_seconds: float | None = None) -> dict:
    """Each video on top, one continuous stretch of library gameplay underneath (muted), looping if it's short.

    ``gameplay`` is the result of media.gameplay.pick() for the total length."""
    videos = _videos(sources)
    if not videos:
        raise PresetError("Add at least one video for the top of the screen.")
    doc = d.document(title or _title_from(videos[0][1]["display_name"]), entry="edit_existing", preset="gameplay",
                     input_kind="files", country=country)
    _add_sources(doc, sources)
    doc["sources"][gameplay["source_id"]] = gameplay["source"]
    doc["segments"][gameplay["segment_id"]] = gameplay["segment"]
    for sid, s in videos:
        scene = _segment_scene(doc, sid, s, entry_seconds, created_by="whole_source" if entry_seconds is None else "manual")
        _with_gameplay(scene, gameplay["segment_id"], layout)
    return doc


def _with_gameplay(scene: dict, seg_id: str, layout: str) -> None:
    scene["layers"]["secondary"] = {"type": "segment", "segment_id": seg_id, "reframe": d.reframe(),
                                    "playback": {**d.playback(), "when_short": "loop", "loop_crossfade_s": 0.25,
                                                 "continue_from_previous": True}}
    if layout == "pip":
        scene["layout"] = {"type": "pip", "background_color": "#000000",
                           "pip": {"inset_layer": "primary", "x": 0.5, "y": 0.12, "width": 0.86, "aspect": "16:9",
                                   "corner_radius_px": 28, "border_px": 4, "border_color": "#FFFFFF"}}
    else:
        scene["layout"] = {"type": "split", "background_color": "#000000",
                           "split": {"divider": 0.5, "primary_position": "top", "gap_px": 0, "gap_color": "#000000"}}
    scene["audio"]["secondary"] = d.mix(False, -24)


# ── create from scratch ──────────────────────────────────────────────────
_SENTENCE = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])")
_USERNAME = re.compile(r"(?<![\w/])/?u/[A-Za-z0-9_-]{3,20}\b")


def split_lines(script: str, min_chars: int = 20, max_chars: int = 220) -> list[str]:
    """Narration lines from a script: paragraphs, then sentences; short sentences join the next one."""
    lines: list[str] = []
    for para in re.split(r"\n\s*\n|\n", script or ""):
        para = normalize_text(para)
        if not para:
            continue
        pending = ""
        for sentence in _SENTENCE.split(para):
            sentence = sentence.strip()
            if not sentence:
                continue
            pending = f"{pending} {sentence}".strip() if pending else sentence
            if len(pending) >= min_chars:
                lines.append(pending)
                pending = ""
        if pending:
            if lines and len(pending) < min_chars and len(lines[-1]) + len(pending) < max_chars:
                lines[-1] = f"{lines[-1]} {pending}"
            else:
                lines.append(pending)
    out = []
    for line in lines:                 # very long sentences are split at commas, keeping each take short
        while len(line) > max_chars and "," in line[: max_chars]:
            cut = line.rfind(",", 0, max_chars) + 1
            out.append(line[:cut].strip())
            line = line[cut:].strip()
        out.append(line)
    return out


def strip_usernames(text: str) -> tuple[str, int]:
    """Replace Reddit usernames (u/name) with "the poster"."""
    count = len(_USERNAME.findall(text or ""))
    return _USERNAME.sub("the poster", text or ""), count


def _narrated_scene(line: str, *, background: str, ranked: bool = False) -> dict:
    scene = {
        "id": new_id("scn"),
        "name": (line[:40] + ("…" if len(line) > 40 else "")),
        "enabled": True,
        "duration": {"driver": "narration", "fixed_s": None, "tail_pad_s": 0.25},
        "layout": {"type": "full", "background_color": "#000000"},
        "layers": {"primary": {"type": "color", "color": background, "reframe": d.reframe()}, "secondary": None},
        "narration": {"text": line[:600], "voice": None, "offset_s": 0.0, "take": None},
        "audio": {"primary": d.mix(False), "secondary": d.mix(False, -24), "narration": d.mix(True),
                  "music": {"enabled": True}},
        "captions": {"mode": "inherit", "manual_cues": [], "word_edits": []},
        "overlays": {"rank_badge": {"visible": ranked}, "label": {"visible": False, "text": None},
                     "reddit_card": None, "texts": []},
        "rank": {"include": ranked},
        "transition_in": {"type": "cut", "duration_s": 0},
        "sfx": [],
    }
    return scene


BACKGROUNDS = ["#14213D", "#1B2A41", "#2B1B3D", "#1D3B2F", "#3B1D1D"]


def story(script: str, *, title: str | None = None, country: str = "US", reddit: dict | None = None,
          gameplay: dict | None = None) -> dict:
    """A narrated story or explainer: one scene per line, captions on the spoken words, music ducked under the voice.

    With ``reddit`` (community, title, source_url) the post title is read over a post card first, and usernames are
    replaced. With ``gameplay`` (from media.gameplay.pick) one continuous stretch of gameplay plays behind it all."""
    replaced = 0
    body = script
    if reddit:
        body, replaced = strip_usernames(body)
    lines = split_lines(body)
    post_title = normalize_text(reddit.get("title", "")) if reddit else ""
    if reddit and post_title:
        post_title, n = strip_usernames(post_title)
        replaced += n
        lines = [post_title] + lines
    if not lines:
        raise PresetError("Paste a script or story with at least one sentence.")
    doc = d.document(title or (post_title or lines[0])[:60], entry="create_from_scratch", preset="story" if not gameplay
                     else "gameplay", input_kind="reddit_post" if reddit else "script", country=country)
    doc["voice"] = d.voice_for(country)
    doc["captions"] = d.captions_on()
    for i, line in enumerate(lines):
        doc["scenes"].append(_narrated_scene(line, background=BACKGROUNDS[i % len(BACKGROUNDS)]))
    if reddit and post_title:
        doc["scenes"][0]["overlays"]["reddit_card"] = {
            "community": (reddit.get("community") or "r/stories")[:40], "title": post_title[:300],
            "author": {"mode": "hidden", "name": None}, "source_url": reddit.get("source_url") or None,
            "show_metrics": False, "metrics": {"upvotes": None, "comments": None}, "start_s": 0.0, "end_s": None}
        if reddit.get("source_url"):
            doc["publish_meta"]["source_links"] = [reddit["source_url"]]
    if gameplay:
        doc["sources"][gameplay["source_id"]] = gameplay["source"]
        doc["segments"][gameplay["segment_id"]] = gameplay["segment"]
        for scene in doc["scenes"]:
            scene["layers"]["primary"] = {"type": "segment", "segment_id": gameplay["segment_id"], "reframe": d.reframe(),
                                          "playback": {**d.playback(), "when_short": "loop", "loop_crossfade_s": 0.25,
                                                       "continue_from_previous": True}}
    doc["extensions"]["import"] = {"usernames_replaced": replaced}
    return doc


def ranking_from_lines(script: str, *, title: str | None = None, country: str = "US",
                       direction: str = "descending") -> dict:
    """A narrated ranking from a list: each line is one entry, read aloud over a coloured card with its badge."""
    lines = [normalize_text(x) for x in (script or "").splitlines() if normalize_text(x)]
    if not lines:
        raise PresetError("Write one entry per line.")
    doc = d.document(title or f"Top {len(lines)}", entry="create_from_scratch", preset="ranking", input_kind="script",
                     country=country)
    doc["voice"] = d.voice_for(country)
    doc["captions"] = d.captions_on()
    doc["ranking"]["enabled"] = True
    doc["ranking"]["direction"] = direction
    doc["overlays"]["title_bar"] = d.title_bar(title or f"Top {len(lines)}")
    for i, line in enumerate(lines):
        scene = _narrated_scene(line, background=BACKGROUNDS[i % len(BACKGROUNDS)], ranked=True)
        scene["overlays"]["label"] = {"visible": True, "text": line[:80]}
        doc["scenes"].append(scene)
    return doc


def blank(*, title: str | None = None, country: str = "US") -> dict:
    doc = d.document(title or "Untitled short", entry="create_from_scratch", preset="blank", input_kind="blank",
                     country=country)
    doc["voice"] = d.voice_for(country)
    scene = _narrated_scene("Your first line.", background=BACKGROUNDS[0])
    scene["narration"] = None
    scene["duration"] = {"driver": "fixed", "fixed_s": 3.0, "tail_pad_s": 0}
    scene["layers"]["primary"] = {"type": "text_card", "reframe": d.reframe(),
                                  "text_card": {"text": "Your text here", "background": "#14213D", "align": "center",
                                                "style": d.text_style(size=110, stroke=0)}}
    scene["name"] = "Scene 1"
    doc["scenes"].append(scene)
    return doc


PRESETS = {"quick_short": quick_short, "blank": from_files, "ranking": ranking}

"""Builders for every part of a version-1 project document, with the app's defaults."""
from __future__ import annotations

from .. import __version__
from ..db import now_iso
from ..ids import new_id

YOUTUBE_SHORTS_INSETS = {"top": 320, "bottom": 400, "left": 60, "right": 180}
QUICK_SHORT_CAP_S = 15.0
QUICK_SHORT_DEFAULT_S = 13.0
QUICK_SHORT_MIN_HINT_S = 12.0


def text_style(font_family: str = "Anton", size: int = 84, color: str = "#FFFFFF", stroke: int = 6,
               box: str | None = None, uppercase: bool = True) -> dict:
    return {"font_family": font_family, "font_size_px": size, "color": color, "stroke_color": "#000000",
            "stroke_px": stroke, "box_color": box, "uppercase": uppercase}


def output() -> dict:
    return {
        "width": 1080, "height": 1920, "fps": 30,
        "video": {"codec": "h264", "encoder": "libx264", "crf": 20, "preset": "medium"},
        "audio": {"codec": "aac", "bitrate_kbps": 192, "sample_rate": 48000,
                  "loudness": {"enabled": True, "target_lufs": -14, "true_peak_dbtp": -1.5, "lra": 11}},
        "when_silent": "omit_audio_stream",
        "max_duration_s": None,
        "safe_area": {"profile": "youtube_shorts", "reference_px": [1080, 1920],
                      "insets_px": dict(YOUTUBE_SHORTS_INSETS)},
    }


def audience(country: str = "US") -> dict:
    ca = country == "CA"
    return {"country": country, "region": None, "language": "en-CA" if ca else "en-US",
            "spelling": "en-CA" if ca else "en-US", "units": "metric" if ca else ("both" if country == "BOTH" else "imperial")}


def compliance() -> dict:
    return {"rights": {"confirmed": False, "confirmed_at": None, "statement_version": 1},
            "reused_content_warning": {"dismissed_at": None}}


def voice(provider: str = "none") -> dict:
    return {"provider": provider, "voice_id": "" if provider == "none" else "en-US-AndrewNeural", "rate_pct": 0}


def ranking() -> dict:
    return {"enabled": False, "direction": "descending",
            "badge": {"format": "#{n}", "position": "top_left", "style": text_style(size=96, stroke=8)},
            "reveal": "current_only"}


def project_audio() -> dict:
    return {"music": None, "ducking": {"enabled": True, "depth_db": -12, "attack_ms": 120, "release_ms": 350},
            "edge_fade_ms": 20}


def captions() -> dict:
    return {"enabled": False, "default_mode": "off",
            "style": {"preset": "bold", "text": text_style(stroke=7), "active_color": "#FFE11A",
                      "emphasis_color": "#4ADE80", "max_words": 3, "max_chars": 18},
            "anchor_y": 0.72, "emphasis_words": []}


def overlays() -> dict:
    return {"hook": None, "title_bar": None, "watermark": None}


def title_bar(text: str) -> dict:
    return {"text": text[:80], "position": "top", "background": "#000000B3", "style": text_style(size=60, stroke=0)}


def hook(text: str) -> dict:
    return {"text": text[:80], "start_s": 0.0, "duration_s": 2.5, "anchor_y": 0.12,
            "style": text_style(size=88, stroke=6, box="#000000B3")}


def voice_for(country: str) -> dict:
    """Default narration voice for the audience: a free Edge voice (needs internet); switch to the system voice
    for offline work."""
    return {"provider": "edge", "voice_id": "en-CA-LiamNeural" if country == "CA" else "en-US-AndrewNeural",
            "rate_pct": 0}


def captions_on() -> dict:
    c = captions()
    c["enabled"] = True
    c["default_mode"] = "narration_words"
    return c


def reframe(mode: str = "fill") -> dict:
    return {"mode": mode, "focus": {"x": 0.5, "y": 0.5}, "zoom": 1.0}


def playback() -> dict:
    return {"speed": 1, "when_short": "freeze_last", "loop_crossfade_s": 0, "continue_from_previous": False}


def mix(enabled: bool, gain_db: float = 0) -> dict:
    return {"enabled": enabled, "gain_db": gain_db, "duck_under_narration": False}


def segment(source_id: str, in_s: float, out_s: float, label: str = "", created_by: str = "manual") -> dict:
    return {"source_id": source_id, "in_s": round(in_s, 3), "out_s": round(out_s, 3), "label": label[:80],
            "created_by": created_by, "pick": None}


def scene_from_segment(segment_id: str, name: str, *, audio_on: bool = True, ranked: bool = False) -> dict:
    return {
        "id": new_id("scn"),
        "name": name[:80],
        "enabled": True,
        "duration": {"driver": "primary", "fixed_s": None, "tail_pad_s": 0},
        "layout": {"type": "full", "background_color": "#000000"},
        "layers": {"primary": {"type": "segment", "segment_id": segment_id, "reframe": reframe(),
                               "playback": playback()},
                   "secondary": None},
        "narration": None,
        "audio": {"primary": mix(audio_on), "secondary": mix(False, -20), "narration": mix(False),
                  "music": {"enabled": False}},
        "captions": {"mode": "inherit", "manual_cues": [], "word_edits": []},
        "overlays": {"rank_badge": {"visible": ranked}, "label": {"visible": ranked, "text": None},
                     "reddit_card": None, "texts": []},
        "rank": {"include": ranked},
        "transition_in": {"type": "cut", "duration_s": 0},
        "sfx": [],
    }


def source_record(kind: str, path: str, display_name: str, fingerprint: dict, *, origin: str = "local_file",
                  ownership: str = "own") -> dict:
    return {"kind": kind, "origin": origin, "ownership": ownership, "path": path, "display_name": display_name[:200],
            "url": None, "attribution": None, "gameplay_clip_id": None, "transcript": None,
            "fingerprint": fingerprint, "imported_at": now_iso()}


def document(title: str, *, entry: str, preset: str, input_kind: str, country: str = "US") -> dict:
    ts = now_iso()
    return {
        "schema": "shorts-studio.project",
        "schema_version": 1,
        "app_version": __version__,
        "id": new_id("prj"),
        "title": (title or "Untitled short")[:120],
        "created_at": ts,
        "updated_at": ts,
        "revision": 0,
        "origin": {"entry": entry, "preset": preset, "input": input_kind},
        "output": output(),
        "audience": audience(country),
        "compliance": compliance(),
        "voice": voice(),
        "sources": {},
        "segments": {},
        "scenes": [],
        "ranking": ranking(),
        "audio": project_audio(),
        "captions": captions(),
        "overlays": overlays(),
        "publish_meta": {"title_drafts": [], "description": "", "tags": [], "source_links": []},
        "extensions": {},
    }

"""Builders for test documents (fingerprints without real files; resolver and plan tests don't touch disk)."""
from __future__ import annotations

import copy

from shorts_studio.project import defaults as d
from shorts_studio.timeline.words import text_sha256


def fp(duration=30.0, w=1920, h=1080, audio=True, sha="0" * 64):
    return {"size_bytes": 1000, "mtime": 1.0, "sample_sha256": sha, "duration_s": duration, "width": w, "height": h,
            "fps": 30, "rotation": 0, "has_audio": audio, "video_codec": "h264", "audio_codec": "aac" if audio else None}


def source(name="clip.mp4", **kw):
    return d.source_record("video", f"C:/v/{name}", name, fp(**kw))


def take(text, duration=2.0, words=None, voice=("edge", "en-US-AndrewNeural", 0), path="data:takes/ab/x.wav"):
    toks = text.split()
    if words is None:
        step = (duration - 0.2) / max(1, len(toks))
        words = [[t, round(0.1 + i * step, 3), round(0.1 + (i + 0.8) * step, 3)] for i, t in enumerate(toks)]
    return {"id": "tk_" + text_sha256(text)[:20], "method": "tts", "provider": voice[0], "voice_id": voice[1],
            "rate_pct": voice[2], "text_sha256": text_sha256(text), "audio_path": path, "duration_s": duration,
            "words": words, "timing": "native", "created_at": "2026-11-25T00:00:00Z"}


def narrate(scene, text, duration=2.0, **kw):
    scene["narration"] = {"text": text, "voice": None, "offset_s": 0.0, "take": take(text, duration, **kw)}
    scene["audio"]["narration"]["enabled"] = True
    scene["duration"]["driver"] = "narration"
    scene["duration"]["tail_pad_s"] = 0.0
    return scene


def ranking_doc(n=3, seconds=4.0):
    doc = d.document("Top", entry="edit_existing", preset="ranking", input_kind="files")
    doc["voice"] = d.voice_for("US")
    doc["ranking"]["enabled"] = True
    for i in range(n):
        sid, seg = f"src_ENTRY{i:05d}", f"seg_ENTRY{i:05d}"
        doc["sources"][sid] = source(f"entry{i}.mp4", sha=f"{i:064d}")
        doc["segments"][seg] = d.segment(sid, 0.0, seconds, f"Entry {i}")
        scene = d.scene_from_segment(seg, f"Entry {i}", ranked=True)
        scene["id"] = f"scn_ENTRY{i:05d}"
        doc["scenes"].append(scene)
    return doc


def with_gameplay(doc, scene_index, seconds=4.0, layout="split"):
    doc["sources"]["src_GAMEPLAY001"] = source("gameplay.mp4", duration=seconds, sha="9" * 64)
    doc["segments"]["seg_GAMEPLAY001"] = d.segment("src_GAMEPLAY001", 0.0, seconds, "Gameplay", "gameplay_pick")
    from shorts_studio.project.presets import _with_gameplay
    _with_gameplay(doc["scenes"][scene_index], "seg_GAMEPLAY001", layout)
    return doc


def clone(doc):
    return copy.deepcopy(doc)

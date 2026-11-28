"""Voice takes, the gameplay library's non-repeating picks, and overlay images staying in the safe area."""
from __future__ import annotations

import random
import socket
import sys

import pytest
from conftest import needs_ffmpeg
from helpers import narrate, ranking_doc

from shorts_studio.media import gameplay
from shorts_studio.render.raster import RasterStore, draw
from shorts_studio.speech import takes
from shorts_studio.testmedia import bands_video
from shorts_studio.timeline.resolve import resolve
from shorts_studio.timeline.words import text_sha256

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows system voice")


def _online() -> bool:
    try:
        socket.create_connection(("speech.platform.bing.com", 443), timeout=3).close()
        return True
    except OSError:
        return False


# ── takes ────────────────────────────────────────────────────────────────
@needs_ffmpeg
@windows_only
def test_system_voice_take_is_offline_timed_and_cached(settings):
    t1 = takes.generate(settings, "He trusted the ladder. The ladder did not trust him.", "system", "", 0)
    assert t1["method"] == "tts" and t1["timing"] == "native" and t1["duration_s"] > 1.5
    assert [w[0] for w in t1["words"]][:3] == ["He", "trusted", "the"]
    assert all(a[1] <= b[1] for a, b in zip(t1["words"], t1["words"][1:]))
    assert t1["text_sha256"] == text_sha256("He trusted the ladder.  The ladder did not trust him.")
    assert settings.resolve_media_path(t1["audio_path"]).is_file()
    t2 = takes.generate(settings, "He trusted the ladder. The ladder did not trust him.", "system", "", 0)
    assert t2 == t1                                                  # the same line is never voiced twice
    t3 = takes.generate(settings, "A different line.", "system", "", 0)
    assert t3["id"] != t1["id"]


@needs_ffmpeg
@windows_only
def test_system_voice_word_times_match_the_audio(settings):
    """SAPI reports positions as if the audio were 16 kHz; the take must still line up with what is heard: the
    word after the sentence pause starts inside that pause, and the last word starts before the audio ends."""
    t = takes.generate(settings, "He trusted the ladder. The ladder did not trust him.", "system", "", 0)
    wav = settings.resolve_media_path(t["audio_path"])
    pauses = [(a, b) for a, b in takes._silences(wav) if 0.2 < a and b < t["duration_s"] - 0.05]
    assert pauses, "expected a pause between the two sentences"
    a, b = max(pauses, key=lambda p: p[1] - p[0])
    second = t["words"][4]
    assert second[0] == "The"
    assert a - 0.05 <= second[1] <= b + 0.1, (second, (a, b))
    assert t["words"][-1][1] < t["duration_s"] - 0.1


@needs_ffmpeg
def test_importing_audio_makes_no_picture_job(settings, db, jobs):
    """Music files have no picture: importing one must not queue a poster job (it used to fail in the background)."""
    import time

    from shorts_studio.media import importer, samples
    f = samples.music_loop(settings.music_dir / samples.MUSIC_NAME, seconds=4)
    (sid, rec), = importer.probe_paths(settings, db, jobs, [str(f)])[0]
    assert rec["kind"] == "audio"
    time.sleep(0.5)
    assert [j for j in db.list_jobs(None) if j["kind"] == "media_prep"] == []
    assert db.get_media(sid)["poster"] is None


@needs_ffmpeg
@pytest.mark.skipif(not _online(), reason="Edge TTS needs the internet")
def test_edge_take_has_native_word_timings(settings):
    t = takes.generate(settings, "Number two: he trusted the ladder.", "edge", "en-US-AndrewNeural", 0)
    assert t["timing"] == "native" and len(t["words"]) == 6
    assert t["words"][0][1] < 0.3 and t["words"][-1][2] <= t["duration_s"]


@needs_ffmpeg
def test_recorded_take_gets_words_pinned_to_pauses(settings, tmp_path):
    from shorts_studio.render.ffmpeg import run
    rec = tmp_path / "rec.wav"
    # Two "phrases" of tone separated by half a second of silence.
    run(["-f", "lavfi", "-i", "sine=f=300:d=1.0", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=0.5",
         "-f", "lavfi", "-i", "sine=f=300:d=1.2", "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", str(rec)])
    t = takes.from_audio(settings, rec, "First part here. Second part here too.", "recorded")
    assert t["method"] == "recorded" and t["timing"] == "estimated"
    words = t["words"]
    first_end = next(w for w in words if w[0] == "here.")[2]
    second_start = next(w for w in words if w[0] == "Second")[1]
    assert 0.9 <= first_end <= 1.1 and 1.4 <= second_start <= 1.6     # the sentence break sits in the pause


def test_take_files_are_only_served_by_key(settings):
    assert takes.take_file(settings, "../../etc/passwd") is None
    assert takes.take_file(settings, "0" * 64 + ".wav") is None


@needs_ffmpeg
def test_retempo_speeds_up_existing_take_and_scales_words(settings, tmp_path):
    from shorts_studio.render.ffmpeg import run
    rec = tmp_path / "voice.wav"
    run(["-f", "lavfi", "-i", "sine=f=300:d=2.0", str(rec)])
    base = takes.from_audio(settings, rec, "Hello fast world.", "recorded")
    words = [["Hello", 0.0, 0.4], ["fast", 0.5, 1.0], ["world.", 1.1, 1.8]]

    fast_125 = takes.retempo(settings, base["audio_path"].rsplit("/", 1)[-1], "Hello fast world.", 1.25, words, "native")
    assert 1.4 <= fast_125["duration_s"] <= 1.8

    # Switching from 1.25x to 1.5x and back to 1.25x must stretch from the 1.0x original, never compounding.
    fast_150 = takes.retempo(settings, fast_125["audio_path"].rsplit("/", 1)[-1], "Hello fast world.", 1.5, fast_125["words"], "native")
    assert 1.1 <= fast_150["duration_s"] <= 1.5
    assert fast_150["timing"] == base["timing"]
    assert fast_150["words"][-1][2] <= fast_150["duration_s"] + 0.01

    back_125 = takes.retempo(settings, fast_150["audio_path"].rsplit("/", 1)[-1], "Hello fast world.", 1.25, fast_150["words"], "native")
    assert back_125["id"] == fast_125["id"]
    assert back_125["duration_s"] == fast_125["duration_s"]

    # 1.0x restores the exact original take.
    reset = takes.retempo(settings, fast_150["audio_path"].rsplit("/", 1)[-1], "Hello fast world.", 1.0, fast_150["words"], "native")
    assert reset["id"] == base["id"]
    assert reset["duration_s"] == base["duration_s"]


# ── gameplay library ─────────────────────────────────────────────────────
def _overlap(a, need, used):
    return sum(max(0.0, min(a + need, u1) - max(a, u0)) for u0, u1 in used)


@pytest.mark.parametrize("seed", range(20))
def test_choose_start_never_repeats_while_a_free_stretch_exists(seed):
    rng = random.Random(seed)
    used: list[tuple[float, float]] = []
    for _ in range(12):
        need = rng.choice([4.0, 6.0, 12.0])
        had_room = any(b - a >= need for a, b in gameplay.free_gaps(60.0, used))
        a = gameplay.choose_start(60.0, need, used, rng)
        assert 0 <= a <= 60 - need
        if had_room:
            assert _overlap(a, need, used) < 1e-6, (a, need, used)
        used.append((a, a + need))


@needs_ffmpeg
def test_library_add_pick_and_remove(settings, db, jobs, media_dir):
    clip_file = bands_video(media_dir / "gp-lib.mp4", seconds=20)
    added, errors = gameplay.add(settings, db, jobs, [str(clip_file)], ["Parkour", "parkour"])
    assert not errors and added[0]["tags"] == ["parkour"]           # tags are trimmed, lower-case, unique
    clip = added[0]
    assert (settings.gameplay_dir / clip["id"]).is_dir()
    first = gameplay.pick(settings, db, clip["id"], 6.0, project_id="prj_TESTTESTTEST", scene_id=None, seed=1)
    second = gameplay.pick(settings, db, clip["id"], 6.0, project_id="prj_TESTTESTTEST", scene_id=None, seed=2)
    assert first["overlap_s"] == 0 and second["overlap_s"] == 0           # 20 s always fits two 6 s stretches
    a, b = sorted([(first["segment"]["in_s"], first["segment"]["out_s"]),
                   (second["segment"]["in_s"], second["segment"]["out_s"])])
    assert b[0] >= a[1] - 1e-6
    assert db.get_clip(clip["id"])["uses"] == 2
    long = gameplay.pick(settings, db, clip["id"], 45.0, project_id=None, scene_id=None, seed=9)
    assert long["loop_needed"] is True and long["segment"]["out_s"] - long["segment"]["in_s"] == pytest.approx(20, abs=0.05)
    assert long["source"]["origin"] == "gameplay_library" and long["source"]["gameplay_clip_id"] == clip["id"]
    gameplay.remove(settings, db, clip["id"])
    assert db.get_clip(clip["id"]) is None and not (settings.gameplay_dir / clip["id"]).exists()


# ── overlay images ───────────────────────────────────────────────────────
def _inside(b, safe):
    x, y, w, h = b
    return x >= safe["x"] - 0.5 and y >= safe["y"] - 0.5 and x + w <= safe["x"] + safe["w"] + 0.5 \
        and y + h <= safe["y"] + safe["h"] + 0.5


def test_every_overlay_stays_inside_the_safe_area(settings, example):
    doc = example("top3-gaming-fails")
    doc["overlays"]["hook"] = {"text": "Wait for number one, it gets so much worse than you think", "start_s": 0,
                               "duration_s": 2.5, "anchor_y": 0.0,
                               "style": {"font_family": "Anton", "font_size_px": 140, "color": "#FFFFFF",
                                         "stroke_color": "#000000", "stroke_px": 8, "box_color": "#000000B3",
                                         "uppercase": True}}
    doc["captions"]["anchor_y"] = 1.0                       # pushed to the very bottom: must be pulled back in
    doc["scenes"][0]["overlays"]["texts"] = [{"id": "ovl_TESTTEXT01", "text": "A very long note " * 6, "start_s": 0,
                                              "end_s": None, "anchor": {"x": 1.0, "y": 1.0},
                                              "style": doc["captions"]["style"]["text"]}]
    doc["scenes"][1]["overlays"]["reddit_card"] = {
        "community": "r/gaming", "title": "Long title " * 20, "author": {"mode": "anonymized", "name": None},
        "source_url": None, "show_metrics": True, "metrics": {"upvotes": 12345, "comments": None},
        "start_s": 0, "end_s": 2.0}
    tl = resolve(doc)
    safe = tl["safe_area"]
    store = RasterStore(settings.raster_dir)
    store.register(tl["rasters"])
    checked = 0
    for rid, spec in tl["rasters"].items():
        if spec["kind"] in ("pip_mask", "pip_border", "text_card", "blank"):
            continue
        meta = store.meta(rid)
        assert _inside(meta["bbox"], safe), (spec["kind"], meta["bbox"], safe)
        checked += 1
    assert checked >= 8


def test_raster_ids_are_stable_and_images_match_the_frame():
    doc = ranking_doc(1)
    a, b = resolve(doc), resolve(doc)
    assert a["rasters"].keys() == b["rasters"].keys()
    spec = next(s for s in a["rasters"].values() if s["kind"] == "badge")
    img, meta = draw(spec)
    assert img.size == (1080, 1920) and img.mode == "RGBA"


def test_post_card_never_invents_numbers():
    doc = ranking_doc(1)
    doc["scenes"][0]["overlays"]["reddit_card"] = {
        "community": "r/stories", "title": "A title", "author": {"mode": "hidden", "name": "secret_user"},
        "source_url": None, "show_metrics": True, "metrics": {"upvotes": None, "comments": None},
        "start_s": 0, "end_s": 1.0}
    narrate(doc["scenes"][0], "A title", duration=1.5)
    tl = resolve(doc)
    spec = next(s for s in tl["rasters"].values() if s["kind"] == "reddit_card")
    assert spec["metrics"] == {"upvotes": None, "comments": None} and spec["author"] is None

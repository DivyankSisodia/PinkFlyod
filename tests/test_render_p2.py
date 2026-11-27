"""Phase 2 workflows rendered for real (offline: generated footage, the Windows system voice, generated music)."""
from __future__ import annotations

import copy
import sys
import time

import pytest
from conftest import frame_rgb, pixel

from shorts_studio.media import gameplay, importer, samples
from shorts_studio.project import presets
from shorts_studio.project.store import ProjectStore
from shorts_studio.render.engine import render_project
from shorts_studio.render.ffmpeg import CancelToken, probe_json
from shorts_studio.render.raster import RasterStore
from shorts_studio.speech import takes
from shorts_studio.testmedia import MARKER_H, MARKER_Y, bands_video, marker_x, solid_video
from shorts_studio.timeline.resolve import resolve

pytestmark = [pytest.mark.render,
              pytest.mark.skipif(sys.platform != "win32", reason="uses the Windows system voice (offline)")]

RED, GREEN, BLUE = (255, 0, 0), (0, 255, 0), (0, 0, 255)


def near(rgb, want, tol=40):
    return all(abs(a - b) <= tol for a, b in zip(rgb, want))


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("p2media")
    return {"red": solid_video(d / "red.mp4", "red", seconds=5, tone_hz=330),
            "green": solid_video(d / "green.mp4", "lime", seconds=5, tone_hz=440),
            "blue": solid_video(d / "blue.mp4", "blue", seconds=6, tone_hz=550),
            "gameplay": bands_video(d / "gameplay-4s.mp4", seconds=4),
            "long_gameplay": bands_video(d / "gameplay-30s.mp4", seconds=30)}


@pytest.fixture
def env(settings, db, jobs):
    store = ProjectStore(settings.projects_dir)

    def imp(*paths):
        sources, errors = importer.probe_paths(settings, db, jobs, [str(p) for p in paths])
        assert not errors, errors
        return sources

    def render(doc):
        return render_project(settings, db, doc, store.renders_dir(doc["id"]), job_id=f"job_{time.time_ns()}",
                              cancel=CancelToken(), progress=lambda p, s: None)

    def voice(doc):
        for s in doc["scenes"]:
            n = s.get("narration")
            if n and n["text"] and (n["take"] is None or resolve_state(doc, s) != "ready"):
                n["take"] = takes.generate(settings, n["text"], doc["voice"]["provider"], doc["voice"]["voice_id"],
                                           doc["voice"]["rate_pct"])
        return doc

    return store, imp, render, voice


def resolve_state(doc, scene):
    from shorts_studio.timeline.resolve import take_state
    return take_state(doc, scene)


def mid(tl, i):
    s = tl["scenes"][i]
    return s["start_s"] + s["duration_s"] / 2


def white_pixels(frame, box):
    x, y, w, h = (int(v) for v in box)
    return sum(1 for yy in range(y, y + h, 3) for xx in range(x, x + w, 3) if min(pixel(frame, xx, yy)) > 215)


# ── 1. silent countdown, reordered after creation ────────────────────────
def test_silent_countdown_reordered(env, settings, clips):
    store, imp, render, _ = env
    doc = presets.ranking(imp(clips["red"], clips["green"], clips["blue"]), title="Silent countdown")
    for s in doc["scenes"]:
        s["audio"]["primary"]["enabled"] = False
    doc["scenes"].append(doc["scenes"].pop(0))              # red moves from #3 to #1
    doc = store.create(doc)
    res = render(doc)
    v = res["verify"]
    assert v["ok"] and v["summary"]["audio_streams"] == 0
    assert [st["codec_type"] for st in probe_json(res["path"])["streams"]] == ["video"]
    tl = resolve(doc)
    assert [s["rank"] for s in tl["scenes"]] == [3, 2, 1]
    rasters = RasterStore(settings.raster_dir)
    for i, colour in enumerate([GREEN, BLUE, RED]):
        frame = frame_rgb(res["path"], mid(tl, i))
        assert near(pixel(frame, 540, 1300), colour), (i, pixel(frame, 540, 1300))
        badge = next(o for o in tl["scenes"][i]["overlays"] if o["kind"] == "badge")
        box = rasters.meta(badge["raster"])["bbox"]
        sa = tl["safe_area"]
        assert box[0] >= sa["x"] and box[1] >= sa["y"] and box[0] + box[2] <= sa["x"] + sa["w"]
        assert white_pixels(frame, box) > 30                  # the rank number is drawn there


# ── 2. narrated explainer: one line edited, only its take redone ─────────
def test_narrated_explainer_line_edit(env, clips):
    store, _imp, render, voice = env
    doc = presets.story("Vancouver gets rain on about 160 days a year. But most of it is light drizzle. "
                        "So pack a light rain jacket.", title="Rain explainer", country="CA")
    doc["voice"] = {"provider": "system", "voice_id": "", "rate_pct": 0}
    doc = store.create(voice(doc))
    first = render(doc)
    assert first["verify"]["ok"]
    ids_before = [s["narration"]["take"]["id"] for s in doc["scenes"]]
    tl_before = resolve(doc)

    doc["scenes"][1]["narration"]["text"] = "But most of it is a light, misty drizzle that barely needs an umbrella."
    assert [i["scene_id"] for i in resolve(doc)["issues"] if i["code"] == "voice_stale"] == [doc["scenes"][1]["id"]]
    doc = voice(doc)
    ids_after = [s["narration"]["take"]["id"] for s in doc["scenes"]]
    assert ids_after[0] == ids_before[0] and ids_after[2] == ids_before[2] and ids_after[1] != ids_before[1]
    doc = store.save(doc["id"], doc, doc["revision"])
    second = render(doc)
    v = second["verify"]
    assert v["ok"] and abs(v["summary"]["loudness"]["integrated_lufs"] + 14) <= 1.0
    assert v["cache_hits"] == 2                               # scenes 1 and 3 were not re-encoded
    tl = resolve(doc)
    assert tl["scenes"][1]["frames"] > tl_before["scenes"][1]["frames"]
    assert tl["scenes"][2]["start_frame"] > tl_before["scenes"][2]["start_frame"]

    # Captions follow the new take: the active (yellow) word is on screen while its word is spoken.
    s2 = tl["scenes"][1]
    words = s2["narration"]["words"]
    for w in (words[2], words[len(words) // 2], words[-2]):
        t = s2["start_s"] + (w[1] + w[2]) / 2
        frame = frame_rgb(second["path"], t)
        yellow = sum(1 for y in range(1000, 1700, 4) for x in range(60, 900, 4)
                     if near(pixel(frame, x, y), (255, 225, 26), 45))
        assert yellow > 20, (w, t, yellow)


# ── 3. split screen with looping, muted gameplay ─────────────────────────
def test_split_screen_with_looping_muted_gameplay(env, settings, db, jobs, clips):
    store, imp, render, _ = env
    clip = gameplay.add(settings, db, jobs, [str(clips["gameplay"])], ["test"])[0][0]
    pick = gameplay.pick(settings, db, clip["id"], 10.0, project_id=None, scene_id=None, seed=1)
    assert pick["loop_needed"] is True
    top = imp(clips["blue"])
    doc = presets.clips_over_gameplay(top, pick)
    scene = doc["scenes"][0]
    seg_id = scene["layers"]["primary"]["segment_id"]
    doc["segments"][seg_id]["out_s"] = 6.0
    scene["duration"] = {"driver": "fixed", "fixed_s": 10.0, "tail_pad_s": 0}
    scene["layers"]["primary"]["playback"]["when_short"] = "freeze_last"
    scene["layers"]["secondary"]["reframe"]["focus"]["x"] = 0.0
    importer.ensure_registered(settings, db, jobs, doc)
    doc = store.create(doc)
    tl = resolve(doc)
    loop = tl["scenes"][0]["layers"][1]["loop"]
    assert loop["joins"] == [3.75, 7.5]
    res = render(doc)
    assert res["verify"]["ok"] and res["verify"]["summary"]["audio_streams"] == 1
    # Bottom half is gameplay; the marker shows the loop restarting after each join.
    row = round(960 + (MARKER_Y * 1080 + MARKER_H / 2) * (960 / 1080))
    kx = 1080 / 1216
    for t, source_t in ((2.0, 2.0), (5.5, 1.75), (8.0, 0.5)):
        frame = frame_rgb(res["path"], t)
        assert near(pixel(frame, 540, 400), BLUE)
        xs = [x for x in range(1080) if min(pixel(frame, x, row)) > 200]
        assert xs, t
        assert abs(sum(xs) / len(xs) - marker_x(source_t) * kx) <= 6, (t, sum(xs) / len(xs), marker_x(source_t) * kx)
    # Muted gameplay contributes no sound: with the top clip's sound off too, there is nothing to hear.
    doc["scenes"][0]["audio"]["primary"]["enabled"] = False
    assert resolve(doc)["audible"] is False


def test_picture_in_picture(env, settings, db, jobs, clips):
    store, imp, render, _ = env
    clip = gameplay.add(settings, db, jobs, [str(clips["long_gameplay"])], [])[0][0]
    pick = gameplay.pick(settings, db, clip["id"], 5.0, project_id=None, scene_id=None, seed=2)
    doc = presets.clips_over_gameplay(imp(clips["red"]), pick, layout="pip")
    importer.ensure_registered(settings, db, jobs, doc)
    doc = store.create(doc)
    tl = resolve(doc)
    inset = next(l for l in tl["scenes"][0]["layers"] if l.get("pip"))
    r = inset["rect"]
    res = render(doc)
    assert res["verify"]["ok"]
    frame = frame_rgb(res["path"], 2.0)
    assert near(pixel(frame, r["x"] + r["w"] // 2, r["y"] + r["h"] // 2), RED)
    assert not near(pixel(frame, r["x"] + 2, r["y"] + 2), RED)              # rounded corner shows the gameplay
    assert not near(pixel(frame, 540, 1700), RED)                            # gameplay fills the rest


# ── 4. the mixed Top 3, then edit only #1 ────────────────────────────────
def test_mixed_top3_and_persistence(env, settings, db, jobs, clips):
    store, imp, render, voice = env
    srcs = imp(clips["red"], clips["green"], clips["blue"])
    doc = presets.ranking(srcs, title="Top 3 funniest gaming fails")
    doc["voice"] = {"provider": "system", "voice_id": "", "rate_pct": 0}
    s3, s2, s1 = doc["scenes"]
    # #3: original sound (as created). #2: narrated, its clip ducked under the voice, music on.
    s2["narration"] = {"text": "Number two. He trusted the ladder. The ladder did not trust him.", "voice": None,
                       "offset_s": 0.2, "take": None}
    s2["audio"]["narration"]["enabled"] = True
    s2["audio"]["primary"].update(gain_db=-6, duck_under_narration=True)
    s2["audio"]["music"]["enabled"] = True
    s2["duration"] = {"driver": "narration", "fixed_s": None, "tail_pad_s": 0.3}
    s2["layers"]["primary"]["playback"]["when_short"] = "loop"
    doc["captions"]["enabled"] = True
    doc["captions"]["default_mode"] = "off"
    s2["captions"]["mode"] = "narration_words"
    music_file = samples.music_loop(settings.music_dir / samples.MUSIC_NAME)
    (mid_, mrec), = importer.probe_paths(settings, db, jobs, [str(music_file)])[0]
    doc["sources"][mid_] = mrec
    doc["audio"]["music"] = {"source_id": mid_, "enabled": True, "gain_db": -16, "start_offset_s": 0, "fade_in_s": 0.3,
                             "fade_out_s": 0.5, "loop": True}
    # #1: above a gameplay split, gameplay muted.
    clip = gameplay.add(settings, db, jobs, [str(clips["long_gameplay"])], [])[0][0]
    pick = gameplay.pick(settings, db, clip["id"], 6.0, project_id=None, scene_id=None, seed=3)
    doc["sources"][pick["source_id"]] = pick["source"]
    doc["segments"][pick["segment_id"]] = pick["segment"]
    presets._with_gameplay(s1, pick["segment_id"], "split")
    importer.ensure_registered(settings, db, jobs, doc)
    doc = store.create(voice(doc))

    first = render(doc)
    v = first["verify"]
    assert v["ok"] and abs(v["summary"]["loudness"]["integrated_lufs"] + 14) <= 1.0
    tl = resolve(doc)
    assert [s["rank"] for s in tl["scenes"]] == [3, 2, 1]
    assert near(pixel(frame_rgb(first["path"], mid(tl, 0)), 540, 1300), RED)
    assert near(pixel(frame_rgb(first["path"], mid(tl, 1)), 540, 1300), GREEN)
    f1 = frame_rgb(first["path"], mid(tl, 2))
    assert near(pixel(f1, 540, 600), BLUE) and not near(pixel(f1, 540, 1500), BLUE)   # split: gameplay below

    # Edit only #1, save, export again.
    before = copy.deepcopy(doc["scenes"][:2])
    doc["scenes"][2]["layout"]["split"]["divider"] = 0.62
    doc = store.save(doc["id"], doc, doc["revision"])
    reopened = store.load(doc["id"]).doc
    assert reopened["scenes"][:2] == before                    # #3 and #2 kept every edit
    second = render(reopened)
    assert second["verify"]["ok"] and second["verify"]["cache_hits"] == 2
    keys1 = [s["cache_key"] for s in first["verify"]["scene_segments"]]
    keys2 = [s["cache_key"] for s in second["verify"]["scene_segments"]]
    assert keys1[:2] == keys2[:2] and keys1[2] != keys2[2]
    for i in (0, 1):
        a, b = frame_rgb(first["path"], mid(tl, i)), frame_rgb(second["path"], mid(tl, i))
        diff = sum(abs(x - y) for x, y in zip(a[::997], b[::997])) / len(a[::997])
        assert diff < 3, (i, diff)
    f2 = frame_rgb(second["path"], mid(tl, 2))
    assert near(pixel(f2, 540, 1150), BLUE) and not near(pixel(f1, 540, 1150), BLUE)   # divider moved down


# ── stills, text cards, Reddit story over gameplay ───────────────────────
def test_reddit_story_over_gameplay_and_text_card(env, settings, db, jobs, clips):
    store, _imp, render, voice = env
    clip = gameplay.add(settings, db, jobs, [str(clips["long_gameplay"])], [])[0][0]
    pick = gameplay.pick(settings, db, clip["id"], 60.0, project_id=None, scene_id=None, seed=4)
    doc = presets.story("I asked u/neighbor_guy to move his car. He said no.",
                        reddit={"community": "r/pettyrevenge", "title": "My neighbor blocked my driveway",
                                "source_url": "https://www.reddit.com/r/pettyrevenge/"}, gameplay=pick)
    doc["voice"] = {"provider": "system", "voice_id": "", "rate_pct": 0}
    blank = presets.blank()
    doc["scenes"].append(blank["scenes"][0])
    importer.ensure_registered(settings, db, jobs, doc)
    doc = store.create(voice(doc))
    tl = resolve(doc)
    assert any(o["kind"] == "reddit_card" for o in tl["scenes"][0]["overlays"])
    res = render(doc)
    assert res["verify"]["ok"]
    card = next(o for o in tl["scenes"][0]["overlays"] if o["kind"] == "reddit_card")
    box = RasterStore(settings.raster_dir).meta(card["raster"])["bbox"]
    frame = frame_rgb(res["path"], (card["start_s"] + card["end_s"]) / 2)
    assert white_pixels(frame, box) > 500                       # the white card is on screen while the title is read
    last = tl["scenes"][-1]
    card_frame = frame_rgb(res["path"], last["start_s"] + 1.0)
    assert near(pixel(card_frame, 20, 20), (0x14, 0x21, 0x3D), 12)          # the text card's background

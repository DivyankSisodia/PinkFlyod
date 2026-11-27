"""The resolver: timing, layouts, loops, ranks, narration, captions, overlays, sound, gates. Pure; no FFmpeg."""
from __future__ import annotations

import copy
import json

from helpers import clone, narrate, ranking_doc, take, with_gameplay

from shorts_studio.timeline import envelope as env
from shorts_studio.timeline.resolve import resolve


def _codes(tl, severity=None):
    return {i["code"] for i in tl["issues"] if severity is None or i["severity"] == severity}


def _quick(example, **seg):
    doc = example("quick-short-13s")
    doc["scenes"][0]["layers"]["primary"]["reframe"].pop("keyframes", None)
    doc["overlays"]["hook"] = None
    doc["segments"]["seg_01JDXLOOKOUT13"].update(seg)
    return doc


def _kinds(scene):
    return [o["kind"] for o in scene["overlays"]]


# ── Phase 1 behaviour still holds ────────────────────────────────────────
def test_quick_short_resolves_to_13_seconds(example):
    tl = resolve(_quick(example))
    assert tl["frames"] == 390 and tl["duration_s"] == 13.0
    assert _codes(tl, "error") == set()
    layer = tl["scenes"][0]["layers"][0]
    assert layer["source_in_s"] == 41.5 and layer["read_s"] == 13.0 and layer["pad_s"] == 0
    assert layer["rect"] == {"x": 0, "y": 0, "w": 1080, "h": 1920}
    assert tl["audible"] is True
    assert tl["safe_area"] == {"x": 60, "y": 320, "w": 840, "h": 1200}


def test_durations_are_whole_frames(example):
    tl = resolve(_quick(example, in_s=0.0, out_s=12.345))
    assert tl["frames"] == 370 and abs(tl["duration_s"] - 370 / 30) < 1e-6


def test_cap(example):
    assert "over_cap" in _codes(resolve(_quick(example, in_s=10.0, out_s=26.0)), "error")
    assert "over_cap" not in _codes(resolve(_quick(example, in_s=10.0, out_s=25.0)))


def test_missing_media_and_rights(example):
    doc = _quick(example)
    assert "media_missing" in _codes(resolve(doc, {"src_01JDXLANDSCAPE": "missing"}), "error")
    doc["sources"]["src_01JDXLANDSCAPE"]["ownership"] = "third_party"
    tl = resolve(doc)
    assert {"rights_unconfirmed"} <= _codes(tl, "error") and "reused_content" in _codes(tl, "warning")
    doc["compliance"]["rights"].update(confirmed=True, confirmed_at="2026-11-25T00:00:00Z")
    assert "rights_unconfirmed" not in _codes(resolve(doc))


def test_resolver_is_pure(example):
    doc = example("top3-gaming-fails")
    snapshot = copy.deepcopy(doc)
    assert resolve(doc) == resolve(doc)
    assert doc == snapshot


# ── the mixed Top 3 example ──────────────────────────────────────────────
def test_top3_resolves_every_feature_it_uses(example):
    tl = resolve(example("top3-gaming-fails"))
    assert _codes(tl, "error") == set()
    assert "not_in_this_build" not in _codes(tl)
    s3, s2, s1 = tl["scenes"]
    assert [s3["rank"], s2["rank"], s1["rank"]] == [3, 2, 1]
    assert [a["track"] for a in s3["audio"]] == ["primary"]                  # #3 keeps its own sound
    assert sorted(a["track"] for a in s2["audio"]) == ["narration", "primary"]
    assert next(a for a in s2["audio"] if a["track"] == "primary")["duck"]  # ducked under the narration
    assert [a["track"] for a in s1["audio"]] == ["primary"]                  # gameplay is muted
    assert s1["layout"]["type"] == "split" and [l["slot"] for l in s1["layers"]] == ["primary", "secondary"]
    assert s1["layers"][1]["loop"] is not None                               # 4 s of gameplay under a 5.8 s scene
    assert "caption" in _kinds(s2) and "caption" not in _kinds(s3) and "caption" not in _kinds(s1)
    assert all("badge" in _kinds(s) for s in tl["scenes"])
    assert [o["kind"] for o in tl["overlays"]] == ["title_bar"]
    assert tl["music"] is not None and len(tl["music"]["envelope"]) > 2
    assert s2["sfx"] == [{"sound": "pop", "at_s": 1.12, "gain_db": -12}]


def test_changing_number_one_leaves_three_and_two_identical(example):
    doc = example("top3-gaming-fails")
    before = resolve(doc)
    changed = copy.deepcopy(doc)
    changed["scenes"][2]["layout"] = {"type": "pip", "background_color": "#000000",
                                      "pip": {"inset_layer": "primary", "x": 0.06, "y": 0.62, "width": 0.45,
                                              "aspect": "16:9", "corner_radius_px": 24, "border_px": 4,
                                              "border_color": "#FFFFFF"}}
    after = resolve(changed)
    assert json.dumps(before["scenes"][:2], sort_keys=True) == json.dumps(after["scenes"][:2], sort_keys=True)
    assert after["scenes"][2]["layout"]["type"] == "pip"


# ── ranking ──────────────────────────────────────────────────────────────
def test_ranks_follow_order_and_direction():
    doc = ranking_doc(4)
    assert [s["rank"] for s in resolve(doc)["scenes"]] == [4, 3, 2, 1]
    doc["ranking"]["direction"] = "ascending"
    assert [s["rank"] for s in resolve(doc)["scenes"]] == [1, 2, 3, 4]


def test_reordering_moves_media_and_label_and_renumbers():
    doc = ranking_doc(3)
    doc["scenes"][0]["overlays"]["label"]["text"] = "Rocket jump"
    moved = clone(doc)
    moved["scenes"].append(moved["scenes"].pop(0))                  # #3 becomes #1
    tl = resolve(moved)
    last = tl["scenes"][-1]
    assert last["id"] == "scn_ENTRY00000" and last["rank"] == 1
    assert last["layers"][0]["source_id"] == "src_ENTRY00000"
    spec = None
    from shorts_studio.timeline.resolve import _Ctx  # noqa: F401 - documents where specs come from
    badge = next(o for o in last["overlays"] if o["kind"] == "badge")
    spec = tl["rasters"][badge["raster"]]
    assert spec["text"] == "#1" and spec["label"] == "Rocket jump"


def test_intro_and_disabled_scenes_are_not_ranked():
    doc = ranking_doc(3)
    doc["scenes"][0]["rank"]["include"] = False
    doc["scenes"][1]["enabled"] = False
    tl = resolve(doc)
    assert [s["rank"] for s in tl["scenes"]] == [None, 1]


def test_list_build_up_reveals_labels_as_entries_play():
    doc = ranking_doc(3)
    doc["ranking"]["reveal"] = "list_build_up"
    tl = resolve(doc)
    rows = [tl["rasters"][s["overlays"][0]["raster"]]["rows"] for s in tl["scenes"]]
    assert [r["n"] for r in rows[0]] == [1, 2, 3]
    assert [bool(r["label"]) for r in rows[0]] == [False, False, True]     # first scene shows #3 only
    assert [bool(r["label"]) for r in rows[2]] == [True, True, True]


def test_silent_ranking_is_not_audible():
    doc = ranking_doc(3)
    for s in doc["scenes"]:
        s["audio"]["primary"]["enabled"] = False
    tl = resolve(doc)
    assert tl["audible"] is False and tl["music"] is None


# ── layouts ──────────────────────────────────────────────────────────────
def test_split_slots_follow_the_divider():
    doc = with_gameplay(ranking_doc(1), 0)
    doc["scenes"][0]["layout"]["split"].update(divider=0.55, gap_px=6)
    s = resolve(doc)["scenes"][0]
    top, bottom = s["layout"]["slots"]["primary"], s["layout"]["slots"]["secondary"]
    assert top == {"x": 0, "y": 0, "w": 1080, "h": 1054} and bottom == {"x": 0, "y": 1060, "w": 1080, "h": 860}
    assert s["layout"]["gap"]["h"] == 6
    assert s["layers"][0]["dst"] == {"x": 0, "y": 0, "w": 1080, "h": 1054}        # each layer fills its own slot
    doc["scenes"][0]["layout"]["split"]["primary_position"] = "bottom"
    s = resolve(doc)["scenes"][0]
    assert s["layout"]["slots"]["primary"]["y"] > 0


def test_independent_reframing_per_layer():
    doc = with_gameplay(ranking_doc(1), 0)
    doc["scenes"][0]["layers"]["primary"]["reframe"]["focus"]["x"] = 0.0
    doc["scenes"][0]["layers"]["secondary"]["reframe"]["focus"]["x"] = 1.0
    a, b = resolve(doc)["scenes"][0]["layers"]
    assert a["src"]["x"] == 0 and b["src"]["x"] + b["src"]["w"] == 1920


def test_pip_rect_and_mask():
    doc = with_gameplay(ranking_doc(1), 0, layout="pip")
    s = resolve(doc)["scenes"][0]
    inset = s["layers"][1] if s["layers"][1]["slot"] == "primary" else s["layers"][0]
    assert s["layers"][0]["rect"] == {"x": 0, "y": 0, "w": 1080, "h": 1920}      # gameplay fills the frame
    assert inset["rect"]["w"] == 928 and inset["rect"]["h"] == 522 and inset["pip"]["mask"]
    assert inset["rect"]["x"] + inset["rect"]["w"] <= 1080


# ── loops and continuity ─────────────────────────────────────────────────
def test_short_gameplay_loops_with_crossfaded_joins():
    doc = with_gameplay(ranking_doc(1, seconds=10.0), 0, seconds=4.0)
    layer = resolve(doc)["scenes"][0]["layers"][1]
    loop = layer["loop"]
    assert len(loop["copies"]) == 3 and loop["crossfade_s"] == 0.25
    assert loop["joins"] == [3.75, 7.5]
    assert sum(c["len_s"] for c in loop["copies"]) - 2 * 0.25 >= 10.0


def test_continue_from_previous_runs_one_stretch_across_scenes():
    doc = ranking_doc(3, seconds=3.0)
    doc = with_gameplay(doc, 0, seconds=20.0)
    for i in (1, 2):
        doc["scenes"][i]["layers"]["secondary"] = copy.deepcopy(doc["scenes"][0]["layers"]["secondary"])
        doc["scenes"][i]["layout"] = copy.deepcopy(doc["scenes"][0]["layout"])
    starts = [s["layers"][1]["source_in_s"] for s in resolve(doc)["scenes"]]
    assert starts == [0.0, 3.0, 6.0]


# ── narration and captions ───────────────────────────────────────────────
def _story():
    doc = ranking_doc(3)
    doc["ranking"]["enabled"] = False
    doc["captions"]["enabled"] = True
    doc["captions"]["default_mode"] = "narration_words"
    for i, s in enumerate(doc["scenes"]):
        s["overlays"]["rank_badge"]["visible"] = s["overlays"]["label"]["visible"] = False
        s["audio"]["primary"]["enabled"] = False
        narrate(s, f"Line number {i} is spoken here.", duration=2.0 + i)
    return doc


def test_narration_drives_scene_length():
    tl = resolve(_story())
    assert [s["frames"] for s in tl["scenes"]] == [60, 90, 120]
    assert [s["start_frame"] for s in tl["scenes"]] == [0, 60, 150]


def test_editing_one_line_marks_only_that_take_stale_and_shifts_later_scenes():
    doc = _story()
    before = resolve(doc)
    doc["scenes"][1]["narration"]["text"] = "Line number one now says something longer."
    stale = resolve(doc)
    assert {(i["code"], i["scene_id"]) for i in stale["issues"] if i["severity"] == "error"} == \
        {("voice_stale", "scn_ENTRY00001")}
    doc["scenes"][1]["narration"]["take"] = take("Line number one now says something longer.", 4.0)
    after = resolve(doc)
    assert _codes(after, "error") == set()
    assert [s["frames"] for s in after["scenes"]] == [60, 120, 120]
    assert after["scenes"][2]["start_frame"] == 180
    strip = lambda s: {k: v for k, v in s.items() if k not in ("start_frame", "start_s")}  # noqa: E731
    assert strip(after["scenes"][0]) == strip(before["scenes"][0])
    assert strip(after["scenes"][2]) == strip(before["scenes"][2])     # same content, only its start moved


def test_changing_the_voice_makes_tts_takes_stale():
    doc = _story()
    doc["voice"]["voice_id"] = "en-CA-LiamNeural"
    assert {i["code"] for i in resolve(doc)["issues"] if i["severity"] == "error"} == {"voice_stale"}


def test_missing_voice_blocks_export():
    doc = _story()
    doc["scenes"][0]["narration"]["take"] = None
    tl = resolve(doc)
    assert "voice_missing" in _codes(tl, "error") and "duration_estimated" in _codes(tl, "warning")


def test_caption_states_follow_the_words():
    doc = _story()
    s = resolve(doc)["scenes"][0]
    caps = [o for o in s["overlays"] if o["kind"] == "caption"]
    words = doc["scenes"][0]["narration"]["take"]["words"]
    assert caps[0]["start_s"] == words[0][1]
    assert all(a["end_s"] <= b["start_s"] + 1e-6 for a, b in zip(caps, caps[1:]))
    assert caps[-1]["end_s"] <= s["duration_s"]


def test_manual_cues_and_word_edits():
    doc = _story()
    doc["scenes"][0]["captions"]["word_edits"] = [{"index": 0, "text": "LINE"}]
    tl = resolve(doc)
    first = next(o for o in tl["scenes"][0]["overlays"] if o["kind"] == "caption")
    assert tl["rasters"][first["raster"]]["words"][0] == "LINE"
    doc["scenes"][1]["captions"] = {"mode": "manual", "manual_cues": [{"start_s": 0.2, "end_s": 1.0, "text": "Hi"}],
                                    "word_edits": []}
    caps = [o for o in resolve(doc)["scenes"][1]["overlays"] if o["kind"] == "caption"]
    assert [(c["start_s"], c["end_s"]) for c in caps] == [(0.2, 1.0)]


def test_reddit_card_hides_while_the_title_is_read():
    doc = _story()
    scene = doc["scenes"][0]
    scene["overlays"]["reddit_card"] = {"community": "r/AmItheAsshole", "title": "Line number 0 is spoken here.",
                                        "author": {"mode": "hidden", "name": "someone"}, "source_url": None,
                                        "show_metrics": False, "metrics": {"upvotes": None, "comments": None},
                                        "start_s": 0.0, "end_s": None}
    tl = resolve(doc)
    card = next(o for o in tl["scenes"][0]["overlays"] if o["kind"] == "reddit_card")
    last_word_end = scene["narration"]["take"]["words"][-1][2]
    assert abs(card["end_s"] - min(2.0, last_word_end + 0.3)) < 1e-6    # never past the end of its scene
    assert tl["rasters"][card["raster"]]["author"] is None
    assert not [o for o in tl["scenes"][0]["overlays"] if o["kind"] == "caption"]


# ── sound ────────────────────────────────────────────────────────────────
def test_music_ducks_under_narration_and_gates_per_scene(example):
    doc = example("top3-gaming-fails")
    tl = resolve(doc)
    m = tl["music"]
    s3, s2, _s1 = tl["scenes"]
    assert env.evaluate(m["envelope"], s3["start_s"] + 1.0) == 0.0             # music off for #3
    words = s2["narration"]["words"]
    mid_speech = s2["start_s"] + (words[1][1] + words[1][2]) / 2
    assert abs(env.evaluate(m["envelope"], mid_speech) - 10 ** (-12 / 20)) < 1e-3   # ducked by 12 dB


def test_envelope_expression_matches_breakpoints():
    pts = env.duck([(1.0, 2.0), (3.0, 3.5)], -12, 0.12, 0.35, 0.0, 5.0)
    expr = env.ffmpeg_expr(pts).replace("gte(t,", "ge(t,")
    import re
    py = re.sub(r"ge\(t,([-\d.]+)\)", r"(t>=\1)", expr)
    py = re.sub(r"lt\(t,([-\d.]+)\)", r"(t<\1)", py)
    for t in [0, 0.5, 0.9, 0.95, 1.5, 2.1, 2.5, 3.2, 3.7, 4.9]:
        assert abs(eval(py, {"t": t}) - env.evaluate(pts, t)) < 1e-4, t   # noqa: S307 - our own expression


def test_hook_title_and_watermark_are_project_overlays(example):
    doc = example("quick-short-13s")
    doc["overlays"]["watermark"] = {"text": "@me", "opacity": 0.6}
    tl = resolve(doc)
    kinds = [(o["kind"], o["start_s"], o["end_s"]) for o in tl["overlays"]]
    assert ("hook", 0, 2.5) in kinds and kinds[-1][0] == "watermark"

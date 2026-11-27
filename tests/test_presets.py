"""Presets build ordinary, valid documents that can be mixed."""
from __future__ import annotations

import copy

import pytest
from helpers import source

from shorts_studio.project import defaults as d
from shorts_studio.project import presets
from shorts_studio.schema import validate_document
from shorts_studio.timeline.resolve import resolve


def _source(kind="video", duration=30.0, has_audio=True, name="clip.mp4"):
    rec = source(name, duration=duration, audio=has_audio)
    if kind == "image":
        rec["kind"] = "image"
        rec["fingerprint"]["duration_s"] = None
    return rec


def _pick(seconds=60.0):
    rec = d.source_record("video", "data:gameplay/gpc_X/game.mp4", "game.mp4",
                          {**source("game.mp4", duration=seconds)["fingerprint"]}, origin="gameplay_library")
    seg = d.segment("src_GAMEPLAYPICK", 10.0, 10.0 + min(seconds - 10, 40), "Game", "gameplay_pick")
    seg["pick"] = {"strategy": "random_nonrepeating", "seed": 5, "picked_at": "2026-11-25T00:00:00Z"}
    return {"source_id": "src_GAMEPLAYPICK", "source": rec, "segment_id": "seg_GAMEPLAYPICK", "segment": seg}


def test_quick_short_defaults():
    doc = presets.quick_short([("src_AAAAAAAAAA", _source())])
    assert validate_document(doc) == []
    assert doc["output"]["max_duration_s"] == 15
    seg = next(iter(doc["segments"].values()))
    assert (seg["in_s"], seg["out_s"]) == (0.0, 13.0)
    assert doc["scenes"][0]["audio"]["primary"]["enabled"] is True


def test_quick_short_needs_a_video():
    with pytest.raises(presets.PresetError):
        presets.quick_short([("src_IMAGEAAAAA", _source("image", name="a.jpg"))])


def test_ranking_preset():
    srcs = [(f"src_ENTRY0000{i}", _source(name=f"fail-{i}.mp4", duration=4 + i)) for i in range(3)]
    doc = presets.ranking(srcs, title="Top 3 fails")
    assert validate_document(doc) == []
    tl = resolve(doc)
    assert [s["rank"] for s in tl["scenes"]] == [3, 2, 1]
    assert doc["overlays"]["title_bar"]["text"] == "Top 3 fails"
    assert all(s["overlays"]["label"]["visible"] for s in doc["scenes"])
    assert [doc["segments"][s["layers"]["primary"]["segment_id"]]["out_s"] for s in doc["scenes"]] == [4, 5, 6]


def test_story_from_script_splits_lines_and_narrates():
    doc = presets.story("Vancouver gets rain on about 160 days a year. But most of it is drizzle.\n\n"
                        "So pack a light jacket. Leave the umbrella.")
    assert validate_document(doc) == []
    lines = [s["narration"]["text"] for s in doc["scenes"]]
    assert lines == ["Vancouver gets rain on about 160 days a year.", "But most of it is drizzle.",
                     "So pack a light jacket. Leave the umbrella."]
    assert all(s["duration"]["driver"] == "narration" for s in doc["scenes"])
    assert doc["captions"]["enabled"] and doc["voice"]["voice_id"] == "en-US-AndrewNeural"
    issues = {i["code"] for i in resolve(doc)["issues"]}
    assert "voice_missing" in issues                       # nothing is voiced until you ask


def test_reddit_story_strips_usernames_and_adds_a_card():
    doc = presets.story("My roommate u/sneaky_pete ate my lunch. I asked /u/sneaky_pete why.",
                        reddit={"community": "r/AmItheAsshole", "title": "AITA for labeling my food?",
                                "source_url": "https://www.reddit.com/r/AmItheAsshole/comments/abc/"},
                        country="CA")
    assert validate_document(doc) == []
    texts = " ".join(s["narration"]["text"] for s in doc["scenes"])
    assert "sneaky_pete" not in texts and texts.count("the poster") == 2
    assert doc["extensions"]["import"]["usernames_replaced"] == 2
    card = doc["scenes"][0]["overlays"]["reddit_card"]
    assert card["author"]["mode"] == "hidden" and card["source_url"].startswith("https://www.reddit.com/")
    assert doc["scenes"][0]["narration"]["text"] == "AITA for labeling my food?"
    assert doc["voice"]["voice_id"] == "en-CA-LiamNeural"
    assert doc["publish_meta"]["source_links"] == [card["source_url"]]


def test_story_over_gameplay_runs_one_continuous_stretch():
    doc = presets.story("First line here is long enough. Second line is also long enough.", gameplay=_pick())
    assert validate_document(doc) == []
    tl = resolve(doc)
    layers = [s["layers"][0] for s in tl["scenes"]]
    assert all(lay["kind"] == "segment" and lay["source_id"] == "src_GAMEPLAYPICK" for lay in layers)
    assert layers[1]["source_in_s"] > layers[0]["source_in_s"]
    assert doc["origin"]["preset"] == "gameplay"


def test_clips_over_gameplay_split_and_pip():
    srcs = [("src_CLIPAAAAAA", _source(duration=8)), ("src_CLIPBBBBBB", _source(duration=5))]
    for layout in ("split", "pip"):
        doc = presets.clips_over_gameplay(srcs, _pick(), layout=layout)
        assert validate_document(doc) == []
        s = doc["scenes"][0]
        assert s["layout"]["type"] == layout and s["layers"]["secondary"]["segment_id"] == "seg_GAMEPLAYPICK"
        assert s["audio"]["secondary"]["enabled"] is False          # gameplay muted by default
        assert {i["code"] for i in resolve(doc)["issues"] if i["severity"] == "error"} == set()


def test_ranking_from_lines_and_blank():
    doc = presets.ranking_from_lines("Pineapple pizza\nCold fries\nWarm soda")
    assert validate_document(doc) == []
    assert [s["overlays"]["label"]["text"] for s in doc["scenes"]] == ["Pineapple pizza", "Cold fries", "Warm soda"]
    blank = presets.blank()
    assert validate_document(blank) == [] and blank["scenes"][0]["layers"]["primary"]["type"] == "text_card"


def test_split_lines_keeps_numbers_and_joins_fragments():
    assert presets.split_lines("It costs $9.99. Really? Yes, really, it does cost that much.") == \
        ["It costs $9.99. Really?", "Yes, really, it does cost that much."]


def test_mixing_presets_in_one_document():
    """A ranking whose #2 is narrated and whose #1 sits over gameplay: three presets' scenes in one document."""
    srcs = [(f"src_ENTRY0000{i}", _source(name=f"fail-{i}.mp4", duration=6)) for i in range(3)]
    doc = presets.ranking(srcs, title="Top 3 funniest gaming fails")
    story = presets.story("He trusted the ladder.")
    doc["scenes"][1]["narration"] = copy.deepcopy(story["scenes"][0]["narration"])
    doc["scenes"][1]["audio"]["narration"]["enabled"] = True
    pick = _pick()
    doc["sources"][pick["source_id"]] = pick["source"]
    doc["segments"][pick["segment_id"]] = pick["segment"]
    presets._with_gameplay(doc["scenes"][2], pick["segment_id"], "split")
    assert validate_document(doc) == []
    tl = resolve(doc)
    assert [s["rank"] for s in tl["scenes"]] == [3, 2, 1]
    assert tl["scenes"][2]["layout"]["type"] == "split"

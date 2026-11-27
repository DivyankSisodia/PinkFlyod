"""The FFmpeg render-graph builder: argument lists and filter graphs for every stage, without running FFmpeg."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from helpers import narrate, ranking_doc, with_gameplay

from shorts_studio.render import plan as P
from shorts_studio.timeline.resolve import resolve

CACHE = Path("C:/cache")


def RP(rid):
    return Path(f"C:/r/{rid}.png")


def PL(key):
    return Path(f"C:/s/{key}.ffconcat")


def paths_for(doc):
    return {sid: Path(f"C:/m/{sid}.mp4") for sid in doc["sources"]}


@pytest.fixture
def quick(example):
    doc = example("quick-short-13s")
    doc["scenes"][0]["layers"]["primary"]["reframe"].pop("keyframes", None)
    doc["overlays"]["hook"] = None
    return doc


def _arg(args, flag, nth=0):
    idx = [i for i, a in enumerate(args) if a == flag][nth]
    return args[idx + 1]


def scmd(doc, i=0):
    tl = resolve(doc)
    return P.scene_command(tl["scenes"][i], tl, paths_for(doc), doc["sources"], CACHE, RP, PL), tl


def test_scene_command_trims_crops_and_counts_frames(quick):
    cmd, tl = scmd(quick)
    a = cmd.args
    assert a[:3] == ["-f", "lavfi", "-i"] and a[3].startswith("color=c=0x000000:s=1080x1920:r=30")
    assert _arg(a, "-ss") == "41.5" and float(_arg(a, "-t")) == pytest.approx(13 + 1 / 30, abs=1e-5)
    s = tl["scenes"][0]["layers"][0]["src"]
    g = cmd.graph
    assert f"crop={s['w']}:{s['h']}:{s['x']}:{s['y']},scale=1080:1920:flags=lanczos" in g
    assert "[b0][L0]overlay=0:0" in g and g.endswith("format=yuv420p[v]")
    assert _arg(a, "-/filter_complex") == P.GRAPH
    assert _arg(a, "-frames:v") == "390" and "-an" in a and _arg(a, "-crf") == "15"
    assert cmd.output == CACHE / f"{cmd.cache_key}.mp4"


def test_cache_key_changes_only_with_the_picture(quick):
    key = scmd(quick)[0].cache_key
    quick["scenes"][0]["audio"]["primary"]["gain_db"] = -6
    quick["title"] = "Renamed"
    quick["scenes"][0]["name"] = "Renamed scene"
    assert scmd(quick)[0].cache_key == key
    quick["sources"]["src_01JDXLANDSCAPE"]["path"] = "D:/moved/hike.mp4"
    assert scmd(quick)[0].cache_key == key                           # same file content, new place
    quick["scenes"][0]["layers"]["primary"]["reframe"]["focus"]["x"] = 0.3
    assert scmd(quick)[0].cache_key != key


def test_fit_and_blur_fill(quick):
    rf = quick["scenes"][0]["layers"]["primary"]["reframe"]
    rf["mode"] = "fit"
    cmd, tl = scmd(quick)
    d = tl["scenes"][0]["layers"][0]["dst"]
    assert f"pad=1080:1920:{d['x']}:{d['y']}:color=0x000000" in cmd.graph
    rf["mode"] = "blur_fill"
    g = scmd(quick)[0].graph
    assert "split=2" in g and "gblur=sigma=6" in g


def test_split_layout_places_both_layers_and_the_gap():
    doc = with_gameplay(ranking_doc(1, seconds=10.0), 0, seconds=4.0)
    doc["scenes"][0]["layout"]["split"].update(divider=0.55, gap_px=6, gap_color="#FFFFFF")
    cmd, tl = scmd(doc)
    g = cmd.graph
    assert "drawbox=x=0:y=1054:w=1080:h=6:color=0xFFFFFF:t=fill" in g
    assert "overlay=0:0:eof_action=repeat" in g and "overlay=0:1060:eof_action=repeat" in g
    assert "scale=1080:1054:flags=lanczos" in g and "scale=1080:860:flags=lanczos" in g


def test_loop_inputs_and_crossfades():
    doc = with_gameplay(ranking_doc(1, seconds=10.0), 0, seconds=4.0)
    cmd, _ = scmd(doc)
    gp = str(Path("C:/m/src_GAMEPLAY001.mp4"))
    assert cmd.args.count(gp) == 3
    offsets = re.findall(r"xfade=transition=fade:duration=0.25:offset=([\d.]+)", cmd.graph)
    assert offsets == ["3.75", "7.5"]


def test_pip_uses_a_rounded_mask_and_border():
    doc = with_gameplay(ranking_doc(1, seconds=6.0), 0, seconds=10.0, layout="pip")
    cmd, tl = scmd(doc)
    inset = next(l for l in tl["scenes"][0]["layers"] if l.get("pip"))
    assert str(RP(inset["pip"]["mask"])) in cmd.args and str(RP(inset["pip"]["border"])) in cmd.args
    assert "alphamerge" in cmd.graph
    r = inset["rect"]
    assert f"overlay={r['x']}:{r['y']}:eof_action=repeat" in cmd.graph


def test_scene_overlays_and_caption_playlist():
    doc = ranking_doc(1)
    doc["captions"]["enabled"] = True
    doc["captions"]["default_mode"] = "narration_words"
    narrate(doc["scenes"][0], "One two three four five six.", duration=3.0)
    cmd, tl = scmd(doc)
    scene = tl["scenes"][0]
    badge = next(o for o in scene["overlays"] if o["kind"] == "badge")
    assert str(RP(badge["raster"])) in cmd.args
    (pl_path, text), = cmd.meta["playlists"].items()
    assert pl_path in cmd.args and text.startswith("ffconcat version 1.0")
    total = sum(float(x) for x in re.findall(r"duration ([\d.]+)", text))
    # The sequence covers the whole scene (a trailing blank, when there is one, runs a second past the end).
    assert abs(total - scene["duration_s"]) < 1e-3 or abs(total - scene["duration_s"] - 1.0) < 1e-3
    assert "[cap]overlay=0:0:eof_action=repeat" in cmd.graph
    assert tl["blank_raster"] in cmd.rasters


def test_caption_track_is_gapless():
    items = P.caption_track([{"raster": "a", "start_s": 0.5, "end_s": 1.0}, {"raster": "b", "start_s": 1.0, "end_s": 1.4}],
                            3.0, lambda r: Path(r), "blank")
    assert [Path(p).name for p, _ in items] == ["blank", "a", "b", "blank"]
    assert [round(d, 3) for _, d in items] == [0.5, 0.5, 0.4, 2.6]


def test_text_card_and_ken_burns(example):
    doc = example("narrated-explainer")
    tl = resolve(doc)
    img = P.scene_command(tl["scenes"][0], tl, paths_for(doc), doc["sources"], CACHE, RP, PL)
    assert "zoompan=z='1+0.1500*on/" in img.graph
    card = P.scene_command(tl["scenes"][2], tl, paths_for(doc), doc["sources"], CACHE, RP, PL)
    assert str(RP(tl["scenes"][2]["layers"][0]["raster"])) in card.args


def test_scene_audio_mixes_clip_narration_and_ducking(example):
    doc = example("top3-gaming-fails")
    tl = resolve(doc)
    cmd = P.scene_audio_command(tl, lambda ev: Path(ev.get("path") or f"C:/m/{ev['source_id']}.mp4"), Path("C:/bed.wav"))
    g = cmd.graph
    assert cmd.args.count("anullsrc=r=48000:cl=stereo") == 3
    assert "adelay=200|200" in g                                    # #2's narration starts 0.2 s in
    assert "volume='lt(t," in g and ":eval=frame" in g              # #2's clip sound ducks under it
    assert "highpass=f=75" in g                                      # voice clean-up on narration
    assert "concat=n=3:v=0:a=1[bed]" in g


def test_music_and_effects(example):
    doc = example("top3-gaming-fails")
    tl = resolve(doc)
    cmd = P.music_and_effects_command(tl, Path("C:/bed.wav"), Path("C:/music.wav"), lambda s: Path(f"C:/fx/{s}.wav"),
                                      Path("C:/mix.wav"))
    assert "-stream_loop" in cmd.args and str(Path("C:/fx/pop.wav")) in cmd.args
    at_ms = int(round((tl["scenes"][1]["start_s"] + 1.12) * 1000))
    assert f"adelay={at_ms}|{at_ms}" in cmd.graph
    assert "volume=-18.00dB" in cmd.graph and ":eval=frame" in cmd.graph
    assert "amix=inputs=3" in cmd.graph
    doc["audio"]["music"] = None
    doc["scenes"][1]["sfx"] = []
    assert P.music_and_effects_command(resolve(doc), Path("C:/bed.wav"), None, lambda s: Path(s), Path("x")) is None


def test_final_command_with_overlays_audio_and_silence(example, quick):
    doc = example("top3-gaming-fails")
    tl = resolve(doc)
    cmd = P.final_command(tl, doc["output"], Path("C:/list.txt"), Path("C:/sound.wav"), Path("C:/out.mp4"), RP)
    title = tl["overlays"][0]["raster"]
    assert str(RP(title)) in cmd.args and "overlay=0:0:format=yuv420[g1]" in cmd.graph
    for flag, value in (("-c:v", "libx264"), ("-crf", "20"), ("-pix_fmt", "yuv420p"), ("-r", "30"),
                        ("-c:a", "aac"), ("-b:a", "192k"), ("-movflags", "+faststart")):
        assert _arg(cmd.args, flag) == value, flag
    assert _arg(cmd.args, "-frames:v") == str(tl["frames"])
    qtl = resolve(quick)
    silent = P.final_command(qtl, quick["output"], Path("C:/l.txt"), None, Path("C:/o.mp4"), RP)
    assert "-an" in silent.args and silent.graph is None and _arg(silent.args, "-map") == "0:v:0"
    quick["output"]["when_silent"] = "silent_aac"
    padded = P.final_command(qtl, quick["output"], Path("C:/l.txt"), None, Path("C:/o.mp4"), RP)
    assert padded.meta["audio"] == "silent" and any(a.startswith("anullsrc") for a in padded.args)


def test_loudness_and_tempo():
    g = P.gain_limit_command(Path("mix.wav"), 6.5, -1.5, Path("out.wav"))
    af = _arg(g.args, "-af")
    assert af.startswith("volume=6.500dB,alimiter=limit=0.79433") and af.endswith("aresample=48000")   # −2.0 dBFS
    assert P.atempo_chain(3.0) == ["atempo=2.0", "atempo=1.500000"]
    assert P.atempo_chain(0.25) == ["atempo=0.5", "atempo=0.500000"]


def test_previews_cut_the_real_segment():
    f = P.frame_from_segment(Path("C:/seg.mp4"), 2.0, Path("C:/f.png"),
                             [{"raster": "rTITLE", "start_s": 0, "end_s": 10}], 5.0, RP, (540, 960))
    assert _arg(f.args, "-ss") == "2" and str(RP("rTITLE")) in f.args and "scale=540:960" in _arg(f.args, "-filter_complex")
    c = P.clip_from_segment(Path("C:/seg.mp4"), 3.0, 4.5, Path("C:/c.mp4"))
    assert _arg(c.args, "-ss") == "3" and _arg(c.args, "-t") == "1.5"


def test_concat_list_escapes_quotes():
    assert "it'\\''s.mp4" in P.concat_list([Path("C:/a/it's.mp4")])

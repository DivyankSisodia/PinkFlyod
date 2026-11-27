"""Real renders through the one pipeline, checked with ffprobe, ebur128 and pixel sampling."""
from __future__ import annotations

import threading
import time

import pytest
from conftest import frame_rgb, pixel

from shorts_studio.project import presets
from shorts_studio.project.store import ProjectStore
from shorts_studio.render.engine import RenderError, render_frame, render_project
from shorts_studio.render.ffmpeg import Cancelled, CancelToken, probe_json
from shorts_studio.testmedia import MARKER_H, MARKER_Y, band_at, bands_video, classify, marker_x

pytestmark = pytest.mark.render


@pytest.fixture
def make(settings, db, imported):
    store = ProjectStore(settings.projects_dir)

    def _make(path, **edits):
        doc = presets.quick_short(imported(path))
        scene = doc["scenes"][0]
        for key, value in edits.items():
            if key == "focus_x":
                scene["layers"]["primary"]["reframe"]["focus"]["x"] = value
            elif key == "mode":
                scene["layers"]["primary"]["reframe"]["mode"] = value
            elif key == "audio":
                scene["audio"]["primary"]["enabled"] = value
            elif key == "trim":
                seg = doc["segments"][scene["layers"]["primary"]["segment_id"]]
                seg["in_s"], seg["out_s"] = value
            elif key == "speed":
                scene["layers"]["primary"]["playback"]["speed"] = value
        return store.create(doc)

    def _render(doc, cancel=None, progress=None):
        return render_project(settings, db, doc, store.renders_dir(doc["id"]), job_id=f"job_{time.time_ns()}",
                              cancel=cancel or CancelToken(), progress=progress or (lambda p, s: None))
    return _make, _render


def test_quick_short_13s_vertical_with_audio(make, landscape):
    build, render = make
    doc = build(landscape, focus_x=0.25, trim=(4.0, 17.0))
    seen = []
    res = render(doc, progress=lambda p, s: seen.append(p))
    s = res["verify"]["summary"]
    assert res["verify"]["ok"], res["verify"]["failed"]
    assert (s["width"], s["height"], s["fps"], s["frames"]) == (1080, 1920, 30.0, 390)
    assert abs(s["video_duration_s"] - 13.0) <= 1 / 30
    assert s["audio_streams"] == 1 and s["audio_codec"] == "aac"
    assert abs(s["loudness"]["integrated_lufs"] - (-14)) <= 1.0
    assert seen == sorted(seen) and seen[-1] == 100
    # Crop check: focus 0.25 puts source column 480 (band 2, yellow) in the middle of the frame.
    frame = frame_rgb(res["path"], 6.0)
    centre = classify(pixel(frame, 540, 1100))
    assert centre == band_at(480) == "yellow"
    # Left edge of the frame shows source column ~176 (band 1, red).
    assert classify(pixel(frame, 8, 1100)) == "red"


def _marker_centre(frame: bytes, row: int) -> float | None:
    xs = [x for x in range(1080) if min(pixel(frame, x, row)) > 200]
    return sum(xs) / len(xs) if xs else None


def test_trim_is_frame_accurate(make, landscape):
    """The sweeping marker shows which source time each exported frame came from (fit mode shows the full width)."""
    build, render = make
    res = render(build(landscape, mode="fit", audio=False, trim=(4.0, 17.0)))
    scale = 1080 / 1920
    row = round(656 + (MARKER_Y * 1080 + MARKER_H / 2) * (608 / 1080))
    for k in (0, 195, 389):                                  # first, middle and last frame
        frame = frame_rgb(res["path"], max(0.0, k / 30 - 0.001))   # input seeking keeps frames starting at or after t
        got = _marker_centre(frame, row)
        want = marker_x(4.0 + k / 30) * scale
        assert got is not None and abs(got - want) <= 5, (k, got, want)   # 5 px ≈ one frame of marker travel


def test_silent_export_has_no_audio_stream(make, landscape):
    build, render = make
    doc = build(landscape, audio=False)
    res = render(doc)
    assert res["verify"]["ok"], res["verify"]["failed"]
    streams = probe_json(res["path"])["streams"]
    assert [st["codec_type"] for st in streams] == ["video"]


def test_source_without_sound_exports_silently(make, landscape_silent):
    build, render = make
    res = render(build(landscape_silent))
    assert res["verify"]["ok"] and res["verify"]["summary"]["audio_streams"] == 0
    assert res["verify"]["summary"]["frames"] == 240


def test_fit_shows_the_whole_frame_with_bars(make, landscape):
    build, render = make
    res = render(build(landscape, mode="fit", audio=False, trim=(0, 3)))
    frame = frame_rgb(res["path"], 1.0)
    assert pixel(frame, 540, 100) == pytest.approx((0, 0, 0), abs=20)           # bar above
    assert classify(pixel(frame, 30, 1100)) == "red"                              # left edge of the source
    assert classify(pixel(frame, 1050, 1100)) == "magenta"                        # right edge of the source


def test_blur_fill_background_is_not_black(make, landscape):
    build, render = make
    res = render(build(landscape, mode="blur_fill", audio=False, trim=(0, 3)))
    assert res["verify"]["ok"]
    top = pixel(frame_rgb(res["path"], 1.0), 540, 300)
    assert sum(top) > 120


def test_speed_doubles_and_halves_length(make, landscape):
    build, render = make
    res = render(build(landscape, trim=(0, 10), speed=2))
    assert res["verify"]["ok"] and res["verify"]["summary"]["frames"] == 150


def test_second_render_reuses_the_cached_scene(make, landscape):
    build, render = make
    doc = build(landscape, trim=(0, 4))
    first = render(doc)
    second = render(doc)
    assert first["verify"]["cache_hits"] == 0 and second["verify"]["cache_hits"] == 1


def test_rotated_phone_video_is_upright(make, media_dir):
    # A 1920×1080 file flagged as rotated 90° is shown as 1080×1920, like a phone recording.
    rotated = bands_video(media_dir / "rotated.mp4", seconds=4, rotation=90)
    build, render = make
    doc = build(rotated, audio=False)
    fp = next(iter(doc["sources"].values()))["fingerprint"]
    assert fp["rotation"] in (90, 270)
    res = render(doc)
    assert res["verify"]["ok"]


def test_cancel_stops_the_render(make, settings, landscape):
    build, render = make
    doc = build(landscape, trim=(0, 15))
    token = CancelToken()
    threading.Timer(0.6, token.cancel).start()
    with pytest.raises(Cancelled):
        render(doc, cancel=token)
    assert not list(settings.scratch_dir.iterdir())
    assert not list(settings.segment_cache_dir.glob("*.part.mp4"))


def test_over_cap_is_refused(make, landscape):
    build, render = make
    doc = build(landscape, trim=(0, 16))
    with pytest.raises(RenderError, match="capped at 15s"):
        render(doc)


def test_exact_frame_matches_the_export(make, settings, landscape, tmp_path):
    build, render = make
    doc = build(landscape, focus_x=0.8, trim=(2, 8), audio=False)
    res = render(doc)
    png = render_frame(settings, doc, 3.0, tmp_path / "f.png", scale=1.0)
    exported, checked = frame_rgb(res["path"], 3.0), frame_rgb(png, 0.0)
    assert classify(pixel(exported, 540, 1100)) == classify(pixel(checked, 540, 1100)) == band_at(0.8 * 1920)
    # The two frames agree everywhere below the moving timestamp strip, within encoding noise.
    diffs = [abs(a - b) for x in range(20, 1080, 106) for y in range(500, 1920, 142)
             for a, b in zip(pixel(exported, x, y), pixel(checked, x, y))]
    assert sum(diffs) / len(diffs) < 8

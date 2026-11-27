"""Crop/placement math. The same fixtures are checked by the frontend (frontend/src/model/geometry.test.ts)."""
from __future__ import annotations

import json

import pytest

from shorts_studio.config import REPO_ROOT
from shorts_studio.timeline.geometry import FIXTURE_CASES, even, fixtures, place

FIXTURE_FILE = REPO_ROOT / "schema" / "fixtures" / "placement-cases.json"


def test_fixture_file_is_current():
    assert json.loads(FIXTURE_FILE.read_text(encoding="utf-8")) == fixtures(), \
        "run: python -m shorts_studio.timeline.geometry --write-fixtures"


def test_even_rounds_half_up():
    assert [even(x) for x in (0, 0.9, 1.0, 1.1, 2.9, 3.0, 607.5, 656.25)] == [0, 0, 2, 2, 2, 4, 608, 656]


@pytest.mark.parametrize("case", FIXTURE_CASES)
def test_placement_invariants(case):
    sw, sh, tw, th, mode, fx, fy, zoom = case
    p = place(*case)
    src, dst = p["src"], p["dst"]
    for v in (*src.values(), *dst.values()):
        assert v % 2 == 0 and v >= 0
    assert src["x"] + src["w"] <= sw and src["y"] + src["h"] <= sh
    assert dst["x"] + dst["w"] <= tw and dst["y"] + dst["h"] <= th
    # Aspect ratio of what you see matches the source window within 1 %.
    assert abs((dst["w"] / dst["h"]) / (src["w"] / src["h"]) - 1) < 0.01
    if mode == "fill":
        assert (dst["w"], dst["h"]) == (tw, th)
    else:
        assert dst["w"] == tw or dst["h"] == th or zoom > 1


def test_landscape_to_vertical_centre_crop():
    p = place(1920, 1080, 1080, 1920, "fill", 0.5, 0.5, 1.0)
    assert p["src"] == {"x": 656, "y": 0, "w": 608, "h": 1080}


def test_focus_is_clamped_at_the_edges():
    left = place(1920, 1080, 1080, 1920, "fill", 0.0, 0.5, 1.0)
    right = place(1920, 1080, 1080, 1920, "fill", 1.0, 0.5, 1.0)
    assert left["src"]["x"] == 0
    assert right["src"]["x"] + right["src"]["w"] == 1920


def test_zoom_tightens_the_crop():
    a = place(1920, 1080, 1080, 1920, "fill", 0.5, 0.5, 1.0)
    b = place(1920, 1080, 1080, 1920, "fill", 0.5, 0.5, 2.0)
    assert b["src"]["w"] == pytest.approx(a["src"]["w"] / 2, abs=2)
    assert b["src"]["h"] == pytest.approx(a["src"]["h"] / 2, abs=2)


def test_fit_letterboxes_landscape():
    p = place(1920, 1080, 1080, 1920, "fit", 0.5, 0.5, 1.0)
    assert p["src"] == {"x": 0, "y": 0, "w": 1920, "h": 1080}
    assert p["dst"] == {"x": 0, "y": 656, "w": 1080, "h": 608}

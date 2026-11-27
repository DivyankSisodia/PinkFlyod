"""Crop and placement math shared with the browser preview.

frontend/src/model/geometry.ts implements the same function, operation for operation, and both are tested
against schema/fixtures/placement-cases.json. Change one, change both, and regenerate the fixtures with
``python -m shorts_studio.timeline.geometry --write-fixtures``.
"""
from __future__ import annotations

import json
import math
import sys


def even(x: float) -> int:
    """Nearest even integer, halves rounded up (the same in Python and JavaScript)."""
    return 2 * math.floor(x / 2 + 0.5)


def even_floor(x: float) -> int:
    return 2 * math.floor(x / 2)


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def place(src_w: int, src_h: int, slot_w: int, slot_h: int, mode: str, focus_x: float, focus_y: float,
          zoom: float) -> dict:
    """Where a source of ``src_w × src_h`` lands in a ``slot_w × slot_h`` slot.

    fill      cover the slot, cropping the source around (focus_x, focus_y); zoom > 1 crops tighter
    fit       show the whole source inside the slot (bars or a blurred copy around it); zoom > 1 grows it
    blur_fill same picture as fit

    Returns integer rectangles: ``src`` = the crop window in source pixels, ``dst`` = where the scaled crop
    goes inside the slot. All values are even so 4:2:0 video never needs rounding by FFmpeg.
    """
    if mode == "fill":
        s = max(slot_w / src_w, slot_h / src_h) * zoom
    else:
        s = min(slot_w / src_w, slot_h / src_h) * zoom
    dw = min(src_w * s, slot_w)
    dh = min(src_h * s, slot_h)
    cw = dw / s
    ch = dh / s
    x0 = _clamp(focus_x * src_w - cw / 2, 0, src_w - cw)
    y0 = _clamp(focus_y * src_h - ch / 2, 0, src_h - ch)

    dw_i = max(2, min(even(dw), even_floor(slot_w)))
    dh_i = max(2, min(even(dh), even_floor(slot_h)))
    cw_i = max(2, min(even(cw), even_floor(src_w)))
    ch_i = max(2, min(even(ch), even_floor(src_h)))
    x_i = max(0, min(even(x0), even_floor(src_w - cw_i)))
    y_i = max(0, min(even(y0), even_floor(src_h - ch_i)))
    dx = even((slot_w - dw_i) / 2)
    dy = even((slot_h - dh_i) / 2)
    return {"src": {"x": x_i, "y": y_i, "w": cw_i, "h": ch_i},
            "dst": {"x": dx, "y": dy, "w": dw_i, "h": dh_i}}


FIXTURE_CASES = [
    # (src_w, src_h, slot_w, slot_h, mode, fx, fy, zoom)
    (1920, 1080, 1080, 1920, "fill", 0.5, 0.5, 1.0),
    (1920, 1080, 1080, 1920, "fill", 0.25, 0.5, 1.0),
    (1920, 1080, 1080, 1920, "fill", 0.0, 0.5, 1.0),
    (1920, 1080, 1080, 1920, "fill", 1.0, 0.5, 1.0),
    (1920, 1080, 1080, 1920, "fill", 0.62, 0.48, 1.15),
    (1920, 1080, 1080, 1920, "fill", 0.5, 0.1, 2.5),
    (3840, 2160, 1080, 1920, "fill", 0.62, 0.48, 1.0),
    (1920, 1080, 1080, 1920, "fit", 0.5, 0.5, 1.0),
    (1920, 1080, 1080, 1920, "blur_fill", 0.5, 0.5, 1.0),
    (1920, 1080, 1080, 1920, "fit", 0.3, 0.5, 1.6),
    (1080, 1920, 1080, 1920, "fill", 0.5, 0.5, 1.0),
    (1080, 1920, 1080, 1920, "fit", 0.5, 0.5, 1.0),
    (720, 1280, 1080, 1920, "fill", 0.5, 0.5, 1.0),
    (1280, 720, 1080, 1056, "fill", 0.5, 0.5, 1.0),
    (1281, 721, 1080, 1920, "fill", 0.5, 0.5, 1.0),
    (640, 480, 1080, 1920, "fit", 0.5, 0.5, 1.0),
    (4032, 3024, 1080, 1920, "fill", 0.5, 0.5, 1.0),
    (1920, 1080, 486, 864, "fill", 0.5, 0.5, 1.0),
]


def fixtures() -> list[dict]:
    return [{"input": {"src_w": c[0], "src_h": c[1], "slot_w": c[2], "slot_h": c[3], "mode": c[4],
                       "focus_x": c[5], "focus_y": c[6], "zoom": c[7]},
             "output": place(*c)} for c in FIXTURE_CASES]


if __name__ == "__main__":  # pragma: no cover
    if "--write-fixtures" in sys.argv:
        from ..config import REPO_ROOT
        dest = REPO_ROOT / "schema" / "fixtures" / "placement-cases.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(fixtures(), indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(FIXTURE_CASES)} cases to {dest}")

# Portions adapted from PurffleShorts (MIT), © 2025 Purffle, commit 514fd25: purffle_shorts/overlays.py
# (font loading with variable-weight axes, `CapStyle` presets, word-highlight caption states drawn with Pillow,
# the forum post card layout from `post_card_png`). Changes: every image is placed inside the Shorts safe area,
# post cards never invent vote or comment counts, and each image is identified by a hash of its spec.
"""Text and shapes drawn once with Pillow and used twice: as overlays in the FFmpeg export and as images in the
browser preview, so on-screen text looks identical in both.

A raster is described by a JSON-able spec; its id is a hash of the spec, so an unchanged caption is never redrawn
and scene segments that use it stay cached. Frame-size rasters are full 1080×1920 RGBA images with the text already
in place, which keeps placement in one function (here) for both consumers.
"""
from __future__ import annotations

import hashlib
import json
import threading
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import REPO_ROOT

RASTER_VERSION = 3
FONT_DIR = REPO_ROOT / "assets" / "fonts"
FONTS = {"anton": "Anton-Regular.ttf", "inter": "Inter-Variable.ttf"}
SYSTEM_FALLBACKS = ["C:/Windows/Fonts/arialbd.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
RANK_COLORS = {1: "#FFD60A", 2: "#D9DEE5", 3: "#E0A060"}


def raster_id(spec: dict) -> str:
    payload = json.dumps({"v": RASTER_VERSION, **spec}, sort_keys=True, ensure_ascii=False)
    return "r" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:31]


# ── fonts ────────────────────────────────────────────────────────────────
def _font_file(family: str) -> str | None:
    name = FONTS.get((family or "").strip().lower(), FONTS["anton"])
    p = FONT_DIR / name
    if p.is_file():
        return str(p)
    for f in SYSTEM_FALLBACKS:
        if Path(f).is_file():
            return f
    return None


_local = threading.local()


def font(family: str, size: int, weight: int = 800) -> ImageFont.FreeTypeFont:
    """Cached per thread: a FreeType face must not be shared between threads."""
    cache = getattr(_local, "fonts", None)
    if cache is None:
        cache = _local.fonts = {}
    key = (family.lower(), max(8, int(size)), weight)
    if key not in cache:
        path = _font_file(family)
        f = ImageFont.truetype(path, key[1]) if path else ImageFont.load_default(size=key[1])
        try:
            axes = f.get_variation_axes()
            values = []
            for ax in axes:
                name = ax.get("name", b"")
                name = name.decode(errors="ignore") if isinstance(name, bytes) else str(name)
                values.append(max(ax["minimum"], min(ax["maximum"], weight)) if "eight" in name
                              else ax.get("default", ax["maximum"]))
            f.set_variation_by_axes(values)
        except Exception:  # noqa: BLE001 - a static font has no axes
            pass
        cache[key] = f
    return cache[key]


def _rgba(color: str | None, default: str = "#000000") -> tuple[int, int, int, int]:
    c = (color or default).lstrip("#")
    if len(c) == 6:
        c += "FF"
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), int(c[6:8], 16)


def _text_w(f: ImageFont.FreeTypeFont, text: str, stroke: int = 0) -> float:
    if not text:
        return 0.0
    box = f.getbbox(text, stroke_width=stroke)
    return box[2] - box[0]


def _wrap(words: list[str], f: ImageFont.FreeTypeFont, width: float, stroke: int) -> list[list[int]]:
    """Indices of ``words`` per line, greedy, never splitting a word."""
    lines: list[list[int]] = [[]]
    space = _text_w(f, "a a", stroke) - _text_w(f, "aa", stroke)
    cur = 0.0
    for i, w in enumerate(words):
        ww = _text_w(f, w, stroke)
        if lines[-1] and cur + space + ww > width:
            lines.append([])
            cur = 0.0
        cur += (space if lines[-1] else 0) + ww
        lines[-1].append(i)
    return [ln for ln in lines if ln]


def _fit(words: list[str], family: str, size: int, weight: int, stroke_ratio: float, width: float,
         max_lines: int, max_height: float) -> tuple[ImageFont.FreeTypeFont, list[list[int]], int]:
    """The largest font size (from ``size`` down) at which the words fit in ``max_lines`` lines and the height."""
    s = size
    while True:
        f = font(family, s, weight)
        stroke = round(s * stroke_ratio)
        lines = _wrap(words, f, width, stroke)
        asc, desc = f.getmetrics()
        height = len(lines) * (asc + desc) * 1.08
        widest = max((_line_width(words, ln, f, stroke) for ln in lines), default=0)
        if (len(lines) <= max_lines and height <= max_height and widest <= width) or s <= 14:
            return f, lines, stroke
        s = int(s * 0.92)


def _line_width(words: list[str], line: list[int], f: ImageFont.FreeTypeFont, stroke: int) -> float:
    return _text_w(f, " ".join(words[i] for i in line), stroke)


def _canvas(spec: dict) -> Image.Image:
    w, h = spec["frame"]
    return Image.new("RGBA", (w, h), (0, 0, 0, 0))


def _clamp_box(x: float, y: float, w: float, h: float, safe: dict) -> tuple[float, float]:
    x = min(max(x, safe["x"]), safe["x"] + safe["w"] - w)
    y = min(max(y, safe["y"]), safe["y"] + safe["h"] - h)
    return x, y


# ── raster kinds ─────────────────────────────────────────────────────────
PRESETS = {
    # stroke ratio, weight, active scale (unused: Phase 2 keeps one size), karaoke colouring
    "bold": {"stroke_ratio": 0.09, "weight": 800, "karaoke": False},
    "boxed": {"stroke_ratio": 0.0, "weight": 800, "karaoke": False},
    "clean": {"stroke_ratio": 0.0, "weight": 700, "karaoke": False, "shadow": True},
    "karaoke": {"stroke_ratio": 0.09, "weight": 800, "karaoke": True},
    "minimal": {"stroke_ratio": 0.06, "weight": 700, "karaoke": False},
}


def _caption(spec: dict, meta: dict) -> Image.Image:
    img = _canvas(spec)
    d = ImageDraw.Draw(img)
    safe = spec["safe"]
    st = spec["style"]
    preset = PRESETS.get(spec.get("preset", "bold"), PRESETS["bold"])
    words = [w.upper() if st["uppercase"] else w for w in spec["words"]]
    stroke_ratio = (st["stroke_px"] / max(1, st["font_size_px"])) if st["stroke_px"] else preset["stroke_ratio"]
    f, lines, stroke = _fit(words, st["font_family"], st["font_size_px"], preset["weight"], stroke_ratio,
                            safe["w"] * 0.94, 3, safe["h"] * 0.4)
    asc, desc = f.getmetrics()
    lh = (asc + desc) * 1.08
    block_h = lh * len(lines)
    cy = safe["y"] + spec["anchor_y"] * safe["h"]
    _, top = _clamp_box(0, cy - block_h / 2, 0, block_h, safe)
    active = spec.get("active")
    fill = _rgba(st["color"], "#FFFFFF")
    stroke_fill = _rgba(st["stroke_color"])
    active_fill = _rgba(spec.get("active_color")) if spec.get("active_color") else None
    emph_fill = _rgba(spec.get("emphasis_color")) if spec.get("emphasis_color") else None
    space = _text_w(f, "a a", stroke) - _text_w(f, "aa", stroke)
    boxes = []
    for li, line in enumerate(lines):
        lw = _line_width(words, line, f, stroke)
        x = safe["x"] + (safe["w"] - lw) / 2
        y = top + li * lh
        if spec.get("preset") == "boxed" and st.get("box_color"):
            pad = f.size * 0.18
            d.rounded_rectangle((x - pad, y - pad * 0.4, x + lw + pad, y + lh - pad * 0.2), radius=pad,
                                fill=_rgba(st["box_color"]))
        for i in line:
            color = fill
            if emph_fill and spec["emphasis"][i]:
                color = emph_fill
            if active_fill is not None and active is not None and (i == active or (preset["karaoke"] and i < active)):
                color = active_fill
            if preset.get("shadow"):
                d.text((x + 3, y + 4), words[i], font=f, fill=(0, 0, 0, 150))
            d.text((x, y), words[i], font=f, fill=color, stroke_width=stroke, stroke_fill=stroke_fill)
            x += _text_w(f, words[i], stroke) + space
        boxes.append((safe["x"] + (safe["w"] - lw) / 2, y, lw, lh))
    meta["bbox"] = _union(boxes)
    return img


def _union(boxes: list[tuple[float, float, float, float]]) -> list[float]:
    if not boxes:
        return [0, 0, 0, 0]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return [round(x0, 1), round(y0, 1), round(x1 - x0, 1), round(y1 - y0, 1)]


def _text_line(d: ImageDraw.ImageDraw, xy, text, f, color, stroke=0, stroke_color="#000000"):
    d.text(xy, text, font=f, fill=_rgba(color), stroke_width=stroke, stroke_fill=_rgba(stroke_color))


def _badge(spec: dict, meta: dict) -> Image.Image:
    """The rank number, and the entry's label under it."""
    img = _canvas(spec)
    d = ImageDraw.Draw(img)
    safe = spec["safe"]
    st = spec["style"]
    top = safe["y"] + spec.get("top_offset", 0) + 8
    boxes = []
    f = font(st["font_family"], st["font_size_px"])
    text = spec["text"].upper() if st["uppercase"] else spec["text"]
    tw = _text_w(f, text, st["stroke_px"])
    asc, desc = f.getmetrics()
    pos = spec.get("position", "top_left")
    x = {"top_left": safe["x"] + 16, "top_center": safe["x"] + (safe["w"] - tw) / 2,
         "top_right": safe["x"] + safe["w"] - tw - 16}[pos]
    if spec.get("show_badge", True):
        if st.get("box_color"):
            d.rounded_rectangle((x - 14, top - 6, x + tw + 14, top + asc + desc), radius=16, fill=_rgba(st["box_color"]))
        _text_line(d, (x, top), text, f, spec.get("color") or st["color"], st["stroke_px"], st["stroke_color"])
        boxes.append((x - 14, top - 6, tw + 28, asc + desc + 6))
        top += asc + desc + 4
    label = spec.get("label")
    if label:
        lf_size = max(28, int(st["font_size_px"] * 0.42))
        words = label.upper().split()
        lf, lines, lstroke = _fit(words, st["font_family"], lf_size, 800, 0.0, safe["w"] * 0.8, 2, safe["h"] * 0.2)
        la, ld = lf.getmetrics()
        lh = (la + ld) * 1.05
        widths = [_line_width(words, ln, lf, 0) for ln in lines]
        bw = max(widths) + 36
        bh = lh * len(lines) + 20
        bx = {"top_left": safe["x"] + 4, "top_center": safe["x"] + (safe["w"] - bw) / 2,
              "top_right": safe["x"] + safe["w"] - bw - 4}[pos]
        bx, by = _clamp_box(bx, top, bw, bh, safe)
        d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=14, fill=(0, 0, 0, 170))
        for k, ln in enumerate(lines):
            _text_line(d, (bx + 18, by + 10 + k * lh), " ".join(words[i] for i in ln), lf, "#FFFFFF")
        boxes.append((bx, by, bw, bh))
    meta["bbox"] = _union(boxes)
    return img


def _rank_list(spec: dict, meta: dict) -> Image.Image:
    """A numbered list that fills in as entries play (the countdown style)."""
    img = _canvas(spec)
    d = ImageDraw.Draw(img)
    safe = spec["safe"]
    st = spec["style"]
    rows = spec["rows"]
    top = safe["y"] + spec.get("top_offset", 0) + 8
    avail = safe["h"] * 0.62
    size = min(st["font_size_px"], int(avail / max(1, len(rows)) / 1.12))
    f = font(st["font_family"], max(24, size))
    asc, desc = f.getmetrics()
    lh = (asc + desc) * 1.08
    numw = _text_w(f, f"{max(r['n'] for r in rows)}.", 0) + 18
    boxes = []
    for k, row in enumerate(rows):
        y = top + k * lh
        x = safe["x"] + 12
        color = RANK_COLORS.get(row["n"], "#FFFFFF")
        _text_line(d, (x, y), f"{row['n']}.", f, color, max(3, size // 14), "#000000")
        if row.get("label"):
            lab = row["label"].upper()
            lf = f
            while _text_w(lf, lab, 3) > safe["w"] - numw - 30 and lf.size > 18:
                lf = font(st["font_family"], int(lf.size * 0.9))
            _text_line(d, (x + numw, y + (asc - lf.getmetrics()[0])), lab, lf,
                       "#FFFFFF" if not row.get("current") else "#FFE11A", max(3, size // 14), "#000000")
        boxes.append((x, y, safe["w"] - 24, lh))
    meta["bbox"] = _union(boxes)
    return img


def _title_bar(spec: dict, meta: dict) -> Image.Image:
    img = _canvas(spec)
    d = ImageDraw.Draw(img)
    safe = spec["safe"]
    st = spec["style"]
    h = spec["height"]
    y = safe["y"] if spec["position"] == "top" else safe["y"] + safe["h"] - h
    if spec.get("background"):
        d.rectangle((0, y, spec["frame"][0], y + h), fill=_rgba(spec["background"]))
    text = spec["text"].upper() if st["uppercase"] else spec["text"]
    s = st["font_size_px"]
    f = font(st["font_family"], s)
    while (_text_w(f, text, st["stroke_px"]) > safe["w"] - 24 or sum(f.getmetrics()) > h - 8) and s > 14:
        s = int(s * 0.93)
        f = font(st["font_family"], s)
    tw = _text_w(f, text, st["stroke_px"])
    asc, desc = f.getmetrics()
    tx = safe["x"] + (safe["w"] - tw) / 2
    ty = y + (h - asc - desc) / 2
    _text_line(d, (tx, ty), text, f, st["color"], st["stroke_px"], st["stroke_color"])
    meta["bbox"] = [round(tx, 1), round(ty, 1), round(tw, 1), round(asc + desc, 1)]
    return img


def _block(spec: dict, meta: dict, words_text: str, cx: float, cy: float, max_w: float, max_lines: int) -> Image.Image:
    img = _canvas(spec)
    d = ImageDraw.Draw(img)
    safe = spec["safe"]
    st = spec["style"]
    words = (words_text.upper() if st["uppercase"] else words_text).split()
    ratio = st["stroke_px"] / max(1, st["font_size_px"])
    f, lines, stroke = _fit(words, st["font_family"], st["font_size_px"], 800, ratio, max_w, max_lines, safe["h"] * 0.5)
    asc, desc = f.getmetrics()
    lh = (asc + desc) * 1.08
    widths = [_line_width(words, ln, f, stroke) for ln in lines]
    bw, bh = max(widths, default=0), lh * len(lines)
    pad = f.size * 0.3 if st.get("box_color") else 0
    x0, y0 = _clamp_box(cx - bw / 2 - pad, cy - bh / 2 - pad, bw + 2 * pad, bh + 2 * pad, safe)
    if st.get("box_color"):
        d.rounded_rectangle((x0, y0, x0 + bw + 2 * pad, y0 + bh + 2 * pad), radius=pad, fill=_rgba(st["box_color"]))
    for k, ln in enumerate(lines):
        lx = x0 + pad + (bw - widths[k]) / 2
        _text_line(d, (lx, y0 + pad + k * lh), " ".join(words[i] for i in ln), f, st["color"], stroke, st["stroke_color"])
    meta["bbox"] = [round(x0, 1), round(y0, 1), round(bw + 2 * pad, 1), round(bh + 2 * pad, 1)]
    return img


def _hook(spec: dict, meta: dict) -> Image.Image:
    safe = spec["safe"]
    return _block(spec, meta, spec["text"], safe["x"] + safe["w"] / 2, safe["y"] + spec["anchor_y"] * safe["h"],
                  safe["w"] * 0.92, 3)


def _text(spec: dict, meta: dict) -> Image.Image:
    safe = spec["safe"]
    return _block(spec, meta, spec["text"], safe["x"] + spec["anchor"]["x"] * safe["w"],
                  safe["y"] + spec["anchor"]["y"] * safe["h"], safe["w"] * 0.9, 4)


def _reddit_card(spec: dict, meta: dict) -> Image.Image:
    img = _canvas(spec)
    d = ImageDraw.Draw(img)
    safe = spec["safe"]
    cw = safe["w"]
    pad = 34
    title_size = 56
    words = spec["title"].split()
    tf, lines, _ = _fit(words, "inter", title_size, 700, 0.0, cw - 2 * pad, 7, safe["h"] * 0.5)
    ta, tdsc = tf.getmetrics()
    lh = (ta + tdsc) * 1.1
    name_f = font("inter", 34, 700)
    meta_f = font("inter", 28, 500)
    av = 64
    head = pad + av + 18
    show_metrics = spec.get("show_metrics") and any(v is not None for v in (spec.get("metrics") or {}).values())
    foot = 60 if show_metrics else 0
    ch = head + lh * len(lines) + (foot + 20 if foot else 0) + pad
    x0 = safe["x"]
    y0 = safe["y"] + safe["h"] * 0.42 - ch / 2
    x0, y0 = _clamp_box(x0, y0, cw, ch, safe)
    d.rounded_rectangle((x0, y0, x0 + cw, y0 + ch), radius=30, fill=(255, 255, 255, 250), outline=(0, 0, 0, 40), width=2)
    d.ellipse((x0 + pad, y0 + pad, x0 + pad + av, y0 + pad + av), fill=(255, 69, 0, 255))
    community = spec.get("community") or "r/stories"
    core = community.split("/", 1)[-1]
    initial_f = font("inter", 34, 800)
    iw = _text_w(initial_f, core[:1].upper() or "?")
    d.text((x0 + pad + (av - iw) / 2, y0 + pad + 10), core[:1].upper() or "?", font=initial_f, fill=(255, 255, 255, 255))
    d.text((x0 + pad + av + 18, y0 + pad + 2), community, font=name_f, fill=(26, 26, 27, 255))
    if spec.get("author"):
        d.text((x0 + pad + av + 18, y0 + pad + 40), spec["author"], font=meta_f, fill=(112, 117, 122, 255))
    y = y0 + head
    for ln in lines:
        d.text((x0 + pad, y), " ".join(words[i] for i in ln), font=tf, fill=(26, 26, 27, 255))
        y += lh
    if show_metrics:
        m = spec["metrics"]
        parts = []
        if m.get("upvotes") is not None:
            parts.append(f"▲ {_compact(m['upvotes'])}")
        if m.get("comments") is not None:
            parts.append(f"{_compact(m['comments'])} comments")
        d.text((x0 + pad, y + 14), "   ".join(parts), font=meta_f, fill=(26, 26, 27, 255))
    meta["bbox"] = [round(x0, 1), round(y0, 1), round(cw, 1), round(ch, 1)]
    return img


def _compact(n: int) -> str:
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def _text_card(spec: dict, meta: dict) -> Image.Image:
    w, h = spec["size"]
    img = Image.new("RGBA", (w, h), _rgba(spec["background"]))
    d = ImageDraw.Draw(img)
    area = spec["text_area"]
    st = spec["style"]
    paragraphs = [p.split() for p in spec["text"].split("\n")]
    flat = [w_ for p in paragraphs for w_ in (p + ["\n"])][:-1]
    words = [x.upper() if st["uppercase"] else x for x in flat if x != "\n"]
    ratio = st["stroke_px"] / max(1, st["font_size_px"])
    f, lines, stroke = _fit(words, st["font_family"], st["font_size_px"], 800, ratio, area["w"] * 0.9, 8, area["h"] * 0.9)
    # Honour explicit line breaks: wrap each paragraph on its own at the size found above.
    lines_out: list[list[str]] = []
    for p in paragraphs:
        pw = [x.upper() if st["uppercase"] else x for x in p]
        for ln in _wrap(pw, f, area["w"] * 0.9, stroke) if pw else [[]]:
            lines_out.append([pw[i] for i in ln])
    asc, desc = f.getmetrics()
    lh = (asc + desc) * 1.1
    bh = lh * len(lines_out)
    y = area["y"] + (area["h"] - bh) / 2
    boxes = []
    for ln in lines_out:
        text = " ".join(ln)
        tw = _text_w(f, text, stroke)
        x = area["x"] + ((area["w"] - tw) / 2 if spec.get("align", "center") == "center" else area["w"] * 0.05)
        _text_line(d, (x, y), text, f, st["color"], stroke, st["stroke_color"])
        boxes.append((x, y, tw, lh))
        y += lh
    meta["bbox"] = _union(boxes)
    return img


def _pip_mask(spec: dict, meta: dict) -> Image.Image:
    w, h = spec["size"]
    img = Image.new("L", (w, h), 0)
    ImageDraw.Draw(img).rounded_rectangle((0, 0, w - 1, h - 1), radius=spec["radius"], fill=255)
    meta["bbox"] = [0, 0, w, h]
    return img


def _pip_border(spec: dict, meta: dict) -> Image.Image:
    w, h = spec["size"]
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    b = spec["border_px"]
    ImageDraw.Draw(img).rounded_rectangle((b / 2, b / 2, w - 1 - b / 2, h - 1 - b / 2), radius=spec["radius"],
                                          outline=_rgba(spec["color"]), width=b)
    meta["bbox"] = [0, 0, w, h]
    return img


def _blank(spec: dict, meta: dict) -> Image.Image:
    meta["bbox"] = [0, 0, 0, 0]
    return _canvas(spec)


KINDS = {"caption": _caption, "badge": _badge, "rank_list": _rank_list, "title_bar": _title_bar, "hook": _hook,
         "text": _text, "reddit_card": _reddit_card, "text_card": _text_card, "pip_mask": _pip_mask,
         "pip_border": _pip_border, "blank": _blank}


def draw(spec: dict) -> tuple[Image.Image, dict]:
    meta: dict = {}
    img = KINDS[spec["kind"]](spec, meta)
    return img, meta


class RasterStore:
    """Specs are registered when a timeline is resolved; images are drawn on first use (preview or export)."""

    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def spec_path(self, rid: str) -> Path:
        return self.folder / rid[1:3] / f"{rid}.json"

    def png_path(self, rid: str) -> Path:
        return self.folder / rid[1:3] / f"{rid}.png"

    def register(self, specs: dict[str, dict]) -> None:
        for rid, spec in specs.items():
            p = self.spec_path(rid)
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_suffix(".tmp")
                tmp.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
                tmp.replace(p)

    def known(self, rid: str) -> bool:
        return self.spec_path(rid).is_file()

    def ensure(self, rid: str) -> Path:
        png = self.png_path(rid)
        if png.is_file():
            return png
        with self._guard:
            lock = self._locks.setdefault(rid, threading.Lock())
        with lock:
            if png.is_file():
                return png
            spec = json.loads(self.spec_path(rid).read_text(encoding="utf-8"))
            img, meta = draw(spec)
            tmp = png.with_suffix(".part.png")
            img.save(tmp, compress_level=3)
            tmp.replace(png)
            png.with_suffix(".meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return png

    def meta(self, rid: str) -> dict:
        self.ensure(rid)
        return json.loads(self.png_path(rid).with_suffix(".meta.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def fonts_available() -> dict[str, bool]:
    return {k: (FONT_DIR / v).is_file() for k, v in FONTS.items()}

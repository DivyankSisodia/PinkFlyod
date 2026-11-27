# Portions adapted from PurffleShorts (MIT), © 2025 Purffle, commit 514fd25: purffle_shorts/render.py
# (`_encode_args` x264 settings, the cover-crop chain and Ken Burns `zoompan` from `prepare_segment`, `xfade` chaining
# from `compose`, PNG playlists through the concat demuxer, the `loudnorm` measurement pass from `mix_audio`, and the
# narration `VOICE_CHAIN`).
"""Turn a resolved timeline into FFmpeg commands. Pure: builds argument lists and filter graphs, runs nothing.

Stage 1  one video-only segment per scene: canvas, layers in their layout slots, scene overlays, captions.
         Cached by a hash of everything that decides its pixels, so an unchanged scene is never re-encoded.
Audio    one pass that builds each scene's sound (clip sound, gameplay sound, narration, ducking) and joins them;
         one pass that lays music and sound effects over it; then a loudness measurement and gain + limiter passes
         (render/engine.py) until it measures -14 LUFS.
Stage 2  one final encode: concat the segments, project-wide overlays (title bar, hook), mux the soundtrack.

Filter graphs are written to files (``-/filter_complex <file>``) because ducking envelopes can be long.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..timeline import envelope as env

PLAN_VERSION = 2          # bump when filters change, so cached segments are rebuilt
INTERMEDIATE = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "15", "-pix_fmt", "yuv420p"]
SAFETY_PAD_FRAMES = 3
GRAPH = "{GRAPH}"         # replaced by the engine with the path of the written filter graph


@dataclass
class Command:
    label: str
    args: list[str]
    output: Path
    duration_s: float = 0.0
    weight: float = 1.0
    loglevel: str = "error"
    cache_key: str | None = None
    graph: str | None = None
    meta: dict = field(default_factory=dict)
    rasters: list[str] = field(default_factory=list)


def _num(x: float) -> str:
    """Seconds for an FFmpeg argument: 6 decimals, trailing zeros dropped."""
    s = f"{x:.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def _hex(color: str) -> str:
    """#RRGGBB[AA] -> FFmpeg 0xRRGGBB[@alpha]."""
    c = color.lstrip("#")
    if len(c) == 8:
        return f"0x{c[:6]}@{int(c[6:], 16) / 255:.3f}"
    return f"0x{c}"


def atempo_chain(speed: float) -> list[str]:
    out, s = [], speed
    while s > 2.0:
        out.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        out.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1.0) > 1e-6:
        out.append(f"atempo={s:.6f}")
    return out


class _Inputs:
    def __init__(self) -> None:
        self.args: list[str] = []
        self.n = 0

    def add(self, *args: str) -> int:
        self.args += list(args)
        self.n += 1
        return self.n - 1


# ── stage 1: one scene ───────────────────────────────────────────────────
def _placement(layer: dict, inp: str, out: str) -> list[str]:
    """Chains taking ``inp`` (the source picture) to a slot-sized picture ``out``."""
    w, h = layer["rect"]["w"], layer["rect"]["h"]
    src, dst = layer["src"], layer["dst"]
    crop = f"crop={src['w']}:{src['h']}:{src['x']}:{src['y']}"
    fg = f"{crop},scale={dst['w']}:{dst['h']}:flags=lanczos,setsar=1"
    if layer["mode"] == "fill":
        if (dst["w"], dst["h"]) == (w, h):
            return [f"[{inp}]{fg}[{out}]"]
        return [f"[{inp}]{fg},pad={w}:{h}:{dst['x']}:{dst['y']}:color={_hex(layer['bar_color'])}[{out}]"]
    if layer["mode"] == "fit":
        return [f"[{inp}]{fg},pad={w}:{h}:{dst['x']}:{dst['y']}:color={_hex(layer['bar_color'])}[{out}]"]
    bg = layer["blur_background"]
    bw, bh = max(2, w // 8 * 2), max(2, h // 8 * 2)
    bcrop = f"crop={bg['src']['w']}:{bg['src']['h']}:{bg['src']['x']}:{bg['src']['y']}"
    return [f"[{inp}]split=2[{out}_f][{out}_b]",
            f"[{out}_b]{bcrop},scale={bw}:{bh},gblur=sigma=6,eq=brightness=-0.06,scale={w}:{h},setsar=1[{out}_bg]",
            f"[{out}_f]{fg}[{out}_fg]",
            f"[{out}_bg][{out}_fg]overlay={dst['x']}:{dst['y']}[{out}]"]


def _tail(layer: dict, fps: int, bg: str) -> str:
    pad = (layer.get("pad_s") or 0) + SAFETY_PAD_FRAMES / fps
    if layer.get("when_short") == "black" and (layer.get("pad_s") or 0) > 0:
        return f"tpad=stop_mode=add:stop_duration={_num(pad)}:color={_hex(bg)}"
    return f"tpad=stop_mode=clone:stop_duration={_num(pad)}"


def _layer_chains(layer: dict, k: int, scene: dict, fps: int, inputs: _Inputs, paths: dict[str, Path],
                  raster_path: Callable[[str], Path]) -> tuple[list[str], str]:
    """Inputs and chains for one layer; returns (chains, label of the slot-sized picture)."""
    dur = scene["frames"] / fps
    w, h = layer["rect"]["w"], layer["rect"]["h"]
    lab = f"L{k}"
    chains: list[str] = []
    kind = layer["kind"]
    if kind == "color":
        i = inputs.add("-f", "lavfi", "-i", f"color=c={_hex(layer['color'] or '#000000')}:s={w}x{h}:r={fps}:d={_num(dur + 1)}")
        chains.append(f"[{i}:v]setsar=1,format=yuv420p[{lab}]")
        return chains, lab
    if kind == "text_card":
        i = inputs.add("-loop", "1", "-framerate", str(fps), "-t", _num(dur + 1), "-i", str(raster_path(layer["raster"])))
        chains.append(f"[{i}:v]scale={w}:{h},setsar=1,format=yuv420p[{lab}]")
        return chains, lab
    if kind == "image":
        path = str(paths[layer["source_id"]])
        if layer["motion"] in ("ken_burns_in", "ken_burns_out"):
            frames = scene["frames"] + SAFETY_PAD_FRAMES
            z = layer["motion_zoom"] - 1
            zexpr = f"1+{z:.4f}*on/{frames}" if layer["motion"] == "ken_burns_in" else f"{1 + z:.4f}-{z:.4f}*on/{frames}"
            src = layer["src"]
            i = inputs.add("-i", path)
            chains.append(f"[{i}:v]crop={src['w']}:{src['h']}:{src['x']}:{src['y']},scale={2 * w}:{2 * h}:flags=lanczos,"
                          f"zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps},"
                          f"setsar=1,format=yuv420p[{lab}]")
            return chains, lab
        i = inputs.add("-loop", "1", "-framerate", str(fps), "-t", _num(dur + 1), "-i", path)
        chains.append(f"[{i}:v]setpts=PTS-STARTPTS,fps={fps}[{lab}_pre]")
        chains += _placement(layer, f"{lab}_pre", f"{lab}_pl")
        chains.append(f"[{lab}_pl]format=yuv420p[{lab}]")
        return chains, lab
    # a clip segment
    path = str(paths[layer["source_id"]])
    speed = layer["speed"]
    retime = "setpts=PTS-STARTPTS" if abs(speed - 1) < 1e-6 else f"setpts=(PTS-STARTPTS)/{speed:.6f}"
    loop = layer.get("loop")
    if loop:
        parts = []
        for j, cp in enumerate(loop["copies"]):
            i = inputs.add("-ss", _num(cp["in_s"]), "-t", _num(cp["len_s"]), "-i", path)
            chains.append(f"[{i}:v]setpts=PTS-STARTPTS,fps={fps},format=yuv420p[{lab}_c{j}]")
            parts.append((f"{lab}_c{j}", cp["len_s"]))
        xf = loop["crossfade_s"]
        if xf > 0:
            acc, last = parts[0][1], parts[0][0]
            for j, (name, length) in enumerate(parts[1:], 1):
                chains.append(f"[{last}][{name}]xfade=transition=fade:duration={_num(xf)}:offset={_num(acc - xf)}[{lab}_x{j}]")
                acc += length - xf
                last = f"{lab}_x{j}"
        else:
            chains.append("".join(f"[{p[0]}]" for p in parts) + f"concat=n={len(parts)}:v=1:a=0[{lab}_cat]")
            last = f"{lab}_cat"
        chains.append(f"[{last}]{retime},fps={fps}[{lab}_pre]")
    else:
        read = max(1.0 / fps, layer["read_s"]) + 1.0 / fps
        i = inputs.add("-ss", _num(layer["source_in_s"]), "-t", _num(read), "-i", path)
        chains.append(f"[{i}:v]{retime},fps={fps}[{lab}_pre]")
    chains += _placement(layer, f"{lab}_pre", f"{lab}_pl")
    chains.append(f"[{lab}_pl]{_tail(layer, fps, scene['background_color'])},format=yuv420p[{lab}]")
    return chains, lab


def _playlist_text(items: list[tuple[str, float]]) -> str:
    lines = ["ffconcat version 1.0"]
    for path, d in items:
        lines += [f"file '{_esc(path)}'", f"duration {_num(d)}"]
    if items:
        lines.append(f"file '{_esc(items[-1][0])}'")
    return "\n".join(lines) + "\n"


def _esc(p: str) -> str:
    return Path(p).resolve().as_posix().replace("'", "'\\''")


def caption_track(overlays: list[dict], dur: float, raster_path: Callable[[str], Path], blank: str) -> list[tuple[str, float]]:
    """Caption states as one gapless sequence of images (blank where no caption shows)."""
    items: list[tuple[str, float]] = []
    t = 0.0
    for ov in sorted(overlays, key=lambda o: o["start_s"]):
        start, end = max(t, ov["start_s"]), min(dur, ov["end_s"])
        if end <= start:
            continue
        if start - t > 1e-4:
            items.append((str(raster_path(blank)), start - t))
        items.append((str(raster_path(ov["raster"])), end - start))
        t = end
    if dur - t > 1e-4:
        items.append((str(raster_path(blank)), dur - t + 1.0))
    return items


def scene_graph(scene: dict, timeline: dict, paths: dict[str, Path], raster_path: Callable[[str], Path],
                playlist_path: Callable[[str], Path]) -> tuple[list[str], str, dict[str, str]]:
    """(input args, filter graph, playlists to write {path: text}) for one scene. Output label is [v]."""
    W, H, fps = timeline["output"]["width"], timeline["output"]["height"], timeline["output"]["fps"]
    dur = scene["frames"] / fps
    inputs = _Inputs()
    chains: list[str] = []
    playlists: dict[str, str] = {}
    canvas = inputs.add("-f", "lavfi", "-i", f"color=c={_hex(scene['background_color'])}:s={W}x{H}:r={fps}:d={_num(dur + 1)}")
    chains.append(f"[{canvas}:v]setsar=1,format=yuv420p[b0]")
    base = "b0"
    gap = scene["layout"].get("gap")
    if gap:
        chains.append(f"[{base}]drawbox=x=0:y={gap['y']}:w={W}:h={gap['h']}:color={_hex(gap['color'])}:t=fill[bgap]")
        base = "bgap"
    for k, layer in enumerate(scene["layers"]):
        lc, lab = _layer_chains(layer, k, scene, fps, inputs, paths, raster_path)
        chains += lc
        r = layer["rect"]
        pip = layer.get("pip")
        if pip and pip.get("mask"):
            m = inputs.add("-loop", "1", "-framerate", str(fps), "-t", _num(dur + 1), "-i", str(raster_path(pip["mask"])))
            chains.append(f"[{m}:v]format=gray,scale={r['w']}:{r['h']}[{lab}_m]")
            chains.append(f"[{lab}]format=yuva420p[{lab}_a];[{lab}_a][{lab}_m]alphamerge[{lab}_r]")
            lab = f"{lab}_r"
        nxt = f"b{k + 1}"
        chains.append(f"[{base}][{lab}]overlay={r['x']}:{r['y']}:eof_action=repeat:format=yuv420[{nxt}]")
        base = nxt
        if pip and pip.get("border"):
            bi = inputs.add("-loop", "1", "-framerate", str(fps), "-t", _num(dur + 1), "-i", str(raster_path(pip["border"])))
            chains.append(f"[{base}][{bi}:v]overlay={r['x']}:{r['y']}:format=yuv420[{nxt}br]")
            base = f"{nxt}br"
    statics = [o for o in scene["overlays"] if o["kind"] != "caption"]
    for j, ov in enumerate(statics):
        i = inputs.add("-loop", "1", "-framerate", str(fps), "-t", _num(dur + 1), "-i", str(raster_path(ov["raster"])))
        enable = "" if ov["start_s"] <= 0 and ov["end_s"] >= dur - 1e-6 else \
            f":enable='between(t,{ov['start_s']:.4f},{ov['end_s'] - 1e-4:.4f})'"
        chains.append(f"[{base}][{i}:v]overlay=0:0:format=yuv420{enable}[o{j}]")
        base = f"o{j}"
    caps = [o for o in scene["overlays"] if o["kind"] == "caption"]
    if caps:
        items = caption_track(caps, dur, raster_path, timeline["blank_raster"])
        key = hashlib.sha256(json.dumps(items).encode()).hexdigest()[:16]
        pl = playlist_path(key)
        playlists[str(pl)] = _playlist_text(items)
        i = inputs.add("-f", "concat", "-safe", "0", "-i", str(pl))
        chains.append(f"[{i}:v]fps={fps},format=rgba[cap]")
        chains.append(f"[{base}][cap]overlay=0:0:eof_action=repeat:format=yuv420[ocap]")
        base = "ocap"
    chains.append(f"[{base}]format=yuv420p[v]")
    return inputs.args, ";\n".join(chains), playlists


def scene_spec(scene: dict, timeline: dict, sources: dict[str, dict]) -> dict:
    """Everything that decides a scene's pixels (not its sound, name or position). Its hash is the cache key."""
    layers = []
    for layer in scene["layers"]:
        entry = {k: v for k, v in layer.items() if k not in ("segment_id",)}
        sid = layer.get("source_id")
        if sid:
            fp = sources[sid]["fingerprint"]
            entry["file"] = {"sha": fp["sample_sha256"], "size": fp["size_bytes"]}
        layers.append(entry)
    return {"v": PLAN_VERSION, "output": timeline["output"], "frames": scene["frames"],
            "background": scene["background_color"], "layout": scene["layout"], "layers": layers,
            "overlays": [{k: o[k] for k in ("kind", "raster", "start_s", "end_s")} for o in scene["overlays"]]}


def cache_key(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode("utf-8")).hexdigest()


def scene_rasters(scene: dict, timeline: dict) -> list[str]:
    ids = [o["raster"] for o in scene["overlays"]]
    for layer in scene["layers"]:
        if layer.get("raster"):
            ids.append(layer["raster"])
        pip = layer.get("pip") or {}
        ids += [x for x in (pip.get("mask"), pip.get("border")) if x]
    if any(o["kind"] == "caption" for o in scene["overlays"]):
        ids.append(timeline["blank_raster"])
    return ids


def scene_command(scene: dict, timeline: dict, paths: dict[str, Path], sources: dict[str, dict], cache_dir: Path,
                  raster_path: Callable[[str], Path], playlist_path: Callable[[str], Path]) -> Command:
    fps = timeline["output"]["fps"]
    key = cache_key(scene_spec(scene, timeline, sources))
    out = cache_dir / f"{key}.mp4"
    inputs, graph, playlists = scene_graph(scene, timeline, paths, raster_path, playlist_path)
    args = [*inputs, "-/filter_complex", GRAPH, "-map", "[v]", "-frames:v", str(scene["frames"]), "-an",
            *INTERMEDIATE, "-r", str(fps), "-g", str(fps), str(out)]
    return Command(f"Scene {scene['index'] + 1}: {scene['name']}", args, out, scene["duration_s"],
                   weight=scene["frames"] * (1 + 0.5 * len(scene["layers"])), cache_key=key, graph=graph,
                   meta={"scene_id": scene["id"], "playlists": playlists}, rasters=scene_rasters(scene, timeline))


def frame_from_segment(segment: Path, t: float, out: Path, project_overlays: list[dict], global_t: float,
                       raster_path: Callable[[str], Path], scale_wh: tuple[int, int]) -> Command:
    """The exact-frame check: a frame of the real stage-1 segment, with the project-wide overlays shown at that time."""
    args = ["-ss", _num(t), "-i", str(segment)]
    chains = ["[0:v]null[f0]"]
    base = "f0"
    active = [o for o in project_overlays if o["start_s"] <= global_t < o["end_s"]]
    for j, ov in enumerate(active, 1):
        args += ["-i", str(raster_path(ov["raster"]))]
        chains.append(f"[{base}][{j}:v]overlay=0:0[f{j}]")
        base = f"f{j}"
    chains.append(f"[{base}]scale={scale_wh[0]}:{scale_wh[1]}:flags=bicubic[v]")
    return Command("Exact frame", [*args, "-filter_complex", ";".join(chains), "-map", "[v]", "-frames:v", "1",
                                   "-f", "image2", "-c:v", "png", str(out)], out)


def clip_from_segment(segment: Path, t0: float, t1: float, out: Path) -> Command:
    """A short video-only cut of a stage-1 segment (used to preview a loop join exactly as exported)."""
    return Command("Preview clip", ["-ss", _num(t0), "-t", _num(max(0.1, t1 - t0)), "-i", str(segment),
                                    "-vf", "scale=540:960", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                                    "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(out)], out)


# ── audio ────────────────────────────────────────────────────────────────
# Gentle broadcast clean-up for narration (from PurffleShorts' VOICE_CHAIN): rumble cut and an even level, so the
# loudness target is reached without hard limiting.
VOICE_CHAIN = ["highpass=f=75", "acompressor=threshold=0.08:ratio=2.5:attack=8:release=140:makeup=1.6"]


def _event_chain(ev: dict, inputs: _Inputs, dur: float, fps: int, rate: int, label: str,
                 path_of: Callable[[dict], Path]) -> list[str]:
    chains: list[str] = []
    fmt = f"asetpts=PTS-STARTPTS,aresample={rate},aformat=sample_fmts=fltp:channel_layouts=stereo"
    copies = ev.get("copies")
    if copies:
        names = []
        for j, cp in enumerate(copies):
            i = inputs.add("-ss", _num(cp["in_s"]), "-t", _num(cp["len_s"]), "-i", str(path_of(ev)))
            chains.append(f"[{i}:a]{fmt}[{label}_c{j}]")
            names.append(f"{label}_c{j}")
        xf = ev.get("crossfade_s") or 0
        last = names[0]
        for j, name in enumerate(names[1:], 1):
            if xf > 0:
                chains.append(f"[{last}][{name}]acrossfade=d={_num(xf)}:c1=tri:c2=tri[{label}_x{j}]")
            else:
                chains.append(f"[{last}][{name}]concat=n=2:v=0:a=1[{label}_x{j}]")
            last = f"{label}_x{j}"
        head = f"[{last}]anull"
    else:
        read = max(1.0 / fps, ev["read_s"]) + (1.0 / fps if ev["track"] != "narration" else 0)
        i = inputs.add("-ss", _num(ev["source_in_s"]), "-t", _num(read), "-i", str(path_of(ev)))
        head = f"[{i}:a]{fmt}"
    parts = [*atempo_chain(ev["speed"])]
    if ev["track"] == "narration":
        parts += VOICE_CHAIN
    if ev["gain_db"]:
        parts.append(f"volume={ev['gain_db']:.2f}dB")
    if ev.get("duck"):
        parts.append(f"volume='{env.ffmpeg_expr(ev['duck'])}':eval=frame")
    f = ev.get("fade_s") or 0
    if f > 0:
        end = min(dur, ev["read_s"] / ev["speed"])
        parts += [f"afade=t=in:st=0:d={_num(f)}", f"afade=t=out:st={_num(max(0.0, end - f))}:d={_num(f)}"]
    if ev["start_s"] > 0:
        ms = int(round(ev["start_s"] * 1000))
        parts.append(f"adelay={ms}|{ms}")
    parts += [f"apad=whole_dur={_num(dur)}", f"atrim=0:{_num(dur)}"]
    chains.append(f"{head},{','.join(parts)}[{label}]")
    return chains


def scene_audio_command(timeline: dict, path_of: Callable[[dict], Path], out: Path, rate: int = 48000) -> Command:
    """Each scene's own sound (clip, gameplay, narration) at its exact length, joined in order."""
    fps = timeline["output"]["fps"]
    inputs = _Inputs()
    chains: list[str] = []
    for i, scene in enumerate(timeline["scenes"]):
        dur = scene["frames"] / fps
        base = inputs.add("-f", "lavfi", "-t", _num(dur), "-i", f"anullsrc=r={rate}:cl=stereo")
        chains.append(f"[{base}:a]aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:{_num(dur)}[s{i}b]")
        labels = [f"s{i}b"]
        for j, ev in enumerate(scene["audio"]):
            lab = f"s{i}e{j}"
            chains += _event_chain(ev, inputs, dur, fps, rate, lab, path_of)
            labels.append(lab)
        if len(labels) == 1:
            chains.append(f"[s{i}b]anull[s{i}]")
        else:
            chains.append("".join(f"[{x}]" for x in labels) +
                          f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,"
                          f"atrim=0:{_num(dur)}[s{i}]")
    n = len(timeline["scenes"])
    chains.append("".join(f"[s{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[bed]")
    args = [*inputs.args, "-/filter_complex", GRAPH, "-map", "[bed]", "-c:a", "pcm_f32le", "-ar", str(rate), str(out)]
    return Command("Scene sound", args, out, timeline["duration_s"], weight=timeline["frames"] * 0.15,
                   graph=";\n".join(chains))


def music_and_effects_command(timeline: dict, bed: Path, music_path: Path | None, sfx_path: Callable[[str], Path],
                              out: Path, rate: int = 48000) -> Command | None:
    """Music (gated per scene, ducked under narration) and sound effects over the scene sound."""
    total = timeline["duration_s"]
    m = timeline["music"]
    cues = [(scene["start_s"] + s["at_s"], s) for scene in timeline["scenes"] for s in scene["sfx"]]
    if not (m and music_path) and not cues:
        return None
    inputs = _Inputs()
    chains = []
    b = inputs.add("-i", str(bed))
    labels = ["bed"]
    chains.append(f"[{b}:a]aformat=sample_fmts=fltp:channel_layouts=stereo[bed]")
    fmt = f"aresample={rate},aformat=sample_fmts=fltp:channel_layouts=stereo"
    if m and music_path:
        loop = ["-stream_loop", "-1"] if m["loop"] else []
        i = inputs.add(*loop, "-ss", _num(m["start_offset_s"]), "-i", str(music_path))
        parts = [fmt, f"volume={m['gain_db']:.2f}dB", f"volume='{env.ffmpeg_expr(m['envelope'])}':eval=frame"]
        if m["fade_in_s"] > 0:
            parts.append(f"afade=t=in:st=0:d={_num(m['fade_in_s'])}")
        if m["fade_out_s"] > 0:
            parts.append(f"afade=t=out:st={_num(max(0.0, total - m['fade_out_s']))}:d={_num(m['fade_out_s'])}")
        parts += [f"apad=whole_dur={_num(total)}", f"atrim=0:{_num(total)}"]
        chains.append(f"[{i}:a]{','.join(parts)}[mus]")
        labels.append("mus")
    for j, (at, s) in enumerate(cues):
        i = inputs.add("-i", str(sfx_path(s["sound"])))
        ms = int(round(at * 1000))
        chains.append(f"[{i}:a]{fmt},volume={s['gain_db']:.2f}dB,adelay={ms}|{ms},apad=whole_dur={_num(total)},"
                      f"atrim=0:{_num(total)}[fx{j}]")
        labels.append(f"fx{j}")
    chains.append("".join(f"[{x}]" for x in labels) +
                  f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,atrim=0:{_num(total)}[mix]")
    args = [*inputs.args, "-/filter_complex", GRAPH, "-map", "[mix]", "-c:a", "pcm_f32le", "-ar", str(rate), str(out)]
    return Command("Music and effects", args, out, total, weight=timeline["frames"] * 0.1, graph=";\n".join(chains))


def loudnorm_filter(loud: dict) -> str:
    return f"loudnorm=I={loud['target_lufs']}:TP={loud['true_peak_dbtp']}:LRA={loud['lra']}"


def loudness_measure_command(mix: Path, loud: dict) -> Command:
    return Command("Measuring loudness", ["-i", str(mix), "-af", f"{loudnorm_filter(loud)}:print_format=json",
                                          "-f", "null", "-"], Path("-"), loglevel="info")


def loudness_apply_command(mix: Path, loud: dict, measured: dict, out: Path, sample_rate: int = 48000) -> Command:
    """loudnorm's own second pass (linear). Kept for reference; the engine uses gain + limiter (below), which also
    reaches the target when speech peaks would force loudnorm into its dynamic mode."""
    m = measured
    af = (f"{loudnorm_filter(loud)}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
          f"linear=true:print_format=json,aresample={sample_rate}")
    return Command("Normalising loudness", ["-i", str(mix), "-af", af, "-c:a", "pcm_f32le", "-ar", str(sample_rate),
                                            str(out)], out, loglevel="info")


LIMITER_HEADROOM_DB = 0.5     # the limiter works on sample peaks; true peaks can sit a little above them


def gain_limit_command(mix: Path, gain_db: float, true_peak_dbtp: float, out: Path, sample_rate: int = 48000) -> Command:
    """One steady gain to the loudness target, with a look-ahead limiter holding peaks under the true-peak ceiling."""
    limit = 10 ** ((true_peak_dbtp - LIMITER_HEADROOM_DB) / 20)
    af = (f"volume={gain_db:.3f}dB,alimiter=limit={limit:.5f}:attack=5:release=60:level=false:latency=true,"
          f"aresample={sample_rate}")
    return Command("Normalising loudness", ["-i", str(mix), "-af", af, "-c:a", "pcm_f32le", "-ar", str(sample_rate),
                                            str(out)], out)


# ── stage 2 ──────────────────────────────────────────────────────────────
def concat_list(segments: list[Path]) -> str:
    return "".join(f"file '{_esc(str(p))}'\n" for p in segments)


def final_command(timeline: dict, output: dict, list_file: Path, soundtrack: Path | None, out: Path,
                  raster_path: Callable[[str], Path] | None = None) -> Command:
    fps = timeline["output"]["fps"]
    total = timeline["duration_s"]
    v = output["video"]
    a = output["audio"]
    inputs = _Inputs()
    inputs.add("-f", "concat", "-safe", "0", "-i", str(list_file))
    audio_mode = "none"
    audio_index = None
    if soundtrack is not None:
        audio_index = inputs.add("-i", str(soundtrack))
        audio_mode = "track"
    elif output["when_silent"] == "silent_aac":
        audio_index = inputs.add("-f", "lavfi", "-t", _num(total), "-i", f"anullsrc=r={a['sample_rate']}:cl=stereo")
        audio_mode = "silent"
    overlays = timeline.get("overlays") or []
    graph = None
    rasters = []
    if overlays and raster_path is not None:
        chains = ["[0:v]setpts=PTS-STARTPTS[g0]"]
        base = "g0"
        for j, ov in enumerate(overlays, 1):
            i = inputs.add("-loop", "1", "-framerate", str(fps), "-t", _num(total + 1), "-i", str(raster_path(ov["raster"])))
            enable = "" if ov["start_s"] <= 0 and ov["end_s"] >= total - 1e-6 else \
                f":enable='between(t,{ov['start_s']:.4f},{ov['end_s'] - 1e-4:.4f})'"
            chains.append(f"[{base}][{i}:v]overlay=0:0:format=yuv420{enable}[g{j}]")
            base = f"g{j}"
            rasters.append(ov["raster"])
        chains.append(f"[{base}]format=yuv420p[v]")
        graph = ";\n".join(chains)
        maps = ["-/filter_complex", GRAPH, "-map", "[v]"]
    else:
        maps = ["-map", "0:v:0"]
    args = [*inputs.args, *maps]
    if audio_index is not None:
        args += ["-map", f"{audio_index}:a:0"]
    args += ["-c:v", "libx264", "-preset", v["preset"], "-crf", str(v["crf"]), "-profile:v", "high",
             "-pix_fmt", "yuv420p", "-r", str(fps), "-g", str(fps * 2), "-frames:v", str(timeline["frames"])]
    if audio_mode != "none":
        args += ["-c:a", "aac", "-b:a", f"{a['bitrate_kbps']}k", "-ar", str(a["sample_rate"]), "-ac", "2"]
    else:
        args += ["-an"]
    args += ["-movflags", "+faststart", str(out)]
    return Command("Final encode", args, out, total, weight=timeline["frames"] * 1.2, graph=graph,
                   meta={"audio": audio_mode}, rasters=rasters)

"""Run a render plan: rasters, stage 1 (cached per scene), sound, stage 2, verification."""
from __future__ import annotations

import logging
import os
import re
import shutil
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ..config import Settings
from ..db import Database
from ..ids import new_id
from ..project.relink import check_sources
from ..timeline.resolve import resolve
from . import plan as P
from . import sfx
from .ffmpeg import CancelToken, loudnorm_report, run
from .raster import RasterStore
from .verify import verify

log = logging.getLogger("shorts_studio.render")
SEGMENT_CACHE_MAX_BYTES = 6 * 1024 ** 3


class RenderError(Exception):
    def __init__(self, message: str, *, issues: list[dict] | None = None, verify: dict | None = None):
        super().__init__(message)
        self.issues = issues or []
        self.verify = verify


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:48].rstrip("-") or "short")


class _Runner:
    """Writes filter graphs and playlists to the scratch folder and runs a Command."""

    def __init__(self, scratch: Path, cancel: CancelToken | None):
        self.scratch = scratch
        self.cancel = cancel
        self.n = 0

    def __call__(self, cmd: P.Command, out: Path | None = None, progress=None, loglevel: str | None = None) -> str:
        args = list(cmd.args)
        if out is not None:
            args[-1] = str(out)
        if cmd.graph is not None:
            self.n += 1
            gp = self.scratch / f"graph-{self.n:03d}.txt"
            gp.write_text(cmd.graph, encoding="utf-8")
            args = [str(gp) if a == P.GRAPH else a for a in args]
        for path, text in (cmd.meta.get("playlists") or {}).items():
            Path(path).write_text(text, encoding="utf-8")
        return run(args, label=cmd.label, cancel=self.cancel, duration=cmd.duration_s if progress else 0.0,
                   progress=progress, loglevel=loglevel or cmd.loglevel)


def _context(settings: Settings, doc: dict, timeline: dict, scratch: Path):
    rasters = RasterStore(settings.raster_dir)
    rasters.register(timeline["rasters"])
    paths = {sid: settings.resolve_media_path(s["path"]) for sid, s in doc["sources"].items()}

    def path_of(ev: dict) -> Path:
        return settings.resolve_media_path(ev["path"]) if ev.get("path") else paths[ev["source_id"]]

    def sfx_path(sound: str) -> Path:
        return paths[sound] if sound.startswith("src_") else sfx.ensure(settings.sfx_dir, sound)

    return rasters, paths, path_of, sfx_path, (lambda key: scratch / f"captions-{key}.ffconcat")


def ensure_segments(settings: Settings, doc: dict, timeline: dict, scratch: Path, cancel: CancelToken | None,
                    report: Callable[[str, float, float], None] | None = None, only: set[str] | None = None) -> tuple[list[Path], int, list[P.Command]]:
    rasters, paths, _path_of, _sfx_path, playlist_path = _context(settings, doc, timeline, scratch)
    runner = _Runner(scratch, cancel)
    settings.segment_cache_dir.mkdir(parents=True, exist_ok=True)
    cmds = [P.scene_command(sc, timeline, paths, doc["sources"], settings.segment_cache_dir, rasters.ensure,
                            playlist_path) for sc in timeline["scenes"] if only is None or sc["id"] in only]
    hits = 0
    out = []
    for cmd in cmds:
        if cancel is not None:
            cancel.check()
        if cmd.output.is_file() and cmd.output.stat().st_size > 0:
            hits += 1
            os.utime(cmd.output)
        else:
            for rid in cmd.rasters:
                rasters.ensure(rid)
            tmp = cmd.output.with_name(f"{cmd.output.stem}.{scratch.name}.part.mp4")
            try:
                runner(cmd, tmp, progress=(lambda f, c=cmd: report(c.label, min(f, 0.999), c.weight)) if report else None)
                os.replace(tmp, cmd.output)
            finally:
                tmp.unlink(missing_ok=True)
        if report:
            report(cmd.label, 1.0, cmd.weight)
        out.append(cmd.output)
    return out, hits, cmds


def render_project(settings: Settings, db: Database, doc: dict, renders_dir: Path, *, job_id: str,
                   cancel: CancelToken, progress: Callable[[float, str], None]) -> dict:
    statuses = check_sources(settings, doc)
    timeline = resolve(doc, statuses)
    blockers = [i for i in timeline["issues"] if i["severity"] == "error"]
    if blockers:
        raise RenderError(blockers[0]["message"], issues=blockers)
    warnings = [i for i in timeline["issues"] if i["severity"] == "warning"]
    output = doc["output"]
    loud = output["audio"]["loudness"]
    frames = timeline["frames"]
    rate = output["audio"]["sample_rate"]

    scratch = settings.scratch_dir / job_id
    scratch.mkdir(parents=True, exist_ok=True)
    rasters, paths, path_of, sfx_path, playlist_path = _context(settings, doc, timeline, scratch)
    runner = _Runner(scratch, cancel)
    seg_weight = sum(sc["frames"] * (1 + 0.5 * len(sc["layers"])) for sc in timeline["scenes"])
    w_audio = frames * 0.3 if timeline["audible"] else 0
    w_final = frames * 1.2
    w_verify = frames * 0.15
    total_w = seg_weight + w_audio + w_final + w_verify
    state = {"done": 0.0}

    def report(stage: str, fraction: float = 0.0, weight: float = 0.0) -> None:
        progress(min(99.0, 100.0 * (state["done"] + fraction * weight) / total_w), stage)

    def seg_report(stage: str, fraction: float, weight: float) -> None:
        if fraction >= 1.0:
            state["done"] += weight
            report(stage)
        else:
            report(stage, fraction, weight)

    started = time.monotonic()
    try:
        segments, hits, scene_cmds = ensure_segments(settings, doc, timeline, scratch, cancel, seg_report)

        soundtrack: Path | None = None
        audio_silent = False
        loudness_report: dict | None = None
        if timeline["audible"]:
            bed = scratch / "scenes.wav"
            report("Scene sound")
            runner(P.scene_audio_command(timeline, path_of, bed, rate))
            mix = bed
            music = timeline["music"]
            mcmd = P.music_and_effects_command(timeline, bed, paths.get(music["source_id"]) if music else None,
                                               sfx_path, scratch / "mix.wav", rate)
            if mcmd is not None:
                report("Music and effects", 0.4, w_audio)
                runner(mcmd)
                mix = mcmd.output
            soundtrack = mix
            if loud["enabled"]:
                report("Measuring loudness", 0.6, w_audio)
                m = P.loudness_measure_command(mix, loud)
                measured = loudnorm_report(runner(m)) or {}
                if not measured or float(measured.get("input_i", "-inf")) <= -70:
                    audio_silent = True
                    warnings.append({"code": "audio_silent", "message": "The sound in this video is silent, so it was "
                                     "not loudness-normalised.", "severity": "warning", "path": "", "scene_id": None})
                else:
                    report("Normalising loudness", 0.8, w_audio)
                    norm = scratch / "soundtrack.wav"
                    loudness_report = _normalise(runner, mix, norm, loud, float(measured["input_i"]), rate)
                    soundtrack = norm
            state["done"] += w_audio

        cancel.check()
        list_file = scratch / "segments.txt"
        list_file.write_text(P.concat_list(segments), encoding="utf-8")
        renders_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        final_path = renders_dir / f"{slug(doc['title'])}-{stamp}.mp4"
        tmp_final = scratch / "final.mp4"
        fcmd = P.final_command(timeline, output, list_file, soundtrack, tmp_final, rasters.ensure)
        for rid in fcmd.rasters:
            rasters.ensure(rid)
        runner(fcmd, progress=lambda f: report("Final encode", f, w_final))
        state["done"] += w_final

        report("Checking the file")
        expect_audio = fcmd.meta["audio"] != "none"
        report_v = verify(tmp_final, width=output["width"], height=output["height"], fps=output["fps"], frames=frames,
                          expect_audio=expect_audio, audio_sample_rate=rate,
                          loudness_target=loud["target_lufs"] if (expect_audio and loud["enabled"]
                                                                  and fcmd.meta["audio"] == "track") else None,
                          audio_silent=audio_silent or fcmd.meta["audio"] == "silent", cancel=cancel)
        if not report_v["ok"]:
            raise RenderError("The exported file failed its checks: " + ", ".join(report_v["failed"]) + ".",
                              verify=report_v)
        shutil.move(str(tmp_final), str(final_path))
        render_id = new_id("rnd")
        report_v["loudness_processing"] = loudness_report
        report_v["render_seconds"] = round(time.monotonic() - started, 2)
        report_v["cache_hits"] = hits
        report_v["scenes"] = len(scene_cmds)
        report_v["scene_segments"] = [{"scene_id": c.meta["scene_id"], "cache_key": c.cache_key} for c in scene_cmds]
        db.insert_render(render_id, doc["id"], doc["revision"], final_path, report_v, warnings)
        progress(100.0, "Done")
        return {"render_id": render_id, "path": str(final_path), "verify": report_v, "warnings": warnings,
                "timeline": {"frames": frames, "duration_s": timeline["duration_s"]}}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        _prune_segment_cache(settings.segment_cache_dir)


LOUDNESS_SETTLE_LU = 0.3


def _normalise(runner: "_Runner", mix: Path, out: Path, loud: dict, measured_i: float, rate: int) -> dict:
    """Gain to the target plus a limiter, then measure the result and correct the gain (at most three passes).
    The limiter only touches peaks, so one correction is normally enough."""
    from .verify import measure_loudness
    target = float(loud["target_lufs"])
    gain = target - measured_i
    passes: list[dict] = []
    for _ in range(5):
        runner(P.gain_limit_command(mix, gain, float(loud["true_peak_dbtp"]), out, rate))
        # The same meter (ebur128) that checks the finished file.
        result = float(measure_loudness(out, runner.cancel, stream="0:a:0").get("integrated_lufs", float("nan")))
        passes.append({"gain_db": round(gain, 2), "result_lufs": result})
        if abs(result - target) <= LOUDNESS_SETTLE_LU:
            break
        # Secant step: where the limiter holds peaks back, 1 dB more gain buys less than 1 LU.
        slope = 1.0
        if len(passes) >= 2 and passes[-1]["gain_db"] != passes[-2]["gain_db"]:
            slope = (passes[-1]["result_lufs"] - passes[-2]["result_lufs"]) / (passes[-1]["gain_db"] - passes[-2]["gain_db"])
            slope = min(1.0, max(0.25, slope))
        gain += min(12.0, (target - result) / slope)
    return {"method": "gain + true-peak limiter", "measured_input_lufs": measured_i, "passes": passes,
            "output_lufs": passes[-1]["result_lufs"]}


def _scene_at(timeline: dict, t: float) -> tuple[dict, float]:
    if not timeline["scenes"]:
        raise RenderError("There is nothing to show yet.")
    fps = timeline["output"]["fps"]
    frame = max(0, min(timeline["frames"] - 1, int(t * fps + 1e-6)))
    scene = next(s for s in timeline["scenes"] if s["start_frame"] <= frame < s["start_frame"] + s["frames"])
    return scene, (frame - scene["start_frame"]) / fps


def _check_media(doc: dict, timeline: dict, scene: dict, settings: Settings) -> None:
    for layer in scene["layers"]:
        sid = layer.get("source_id")
        if sid and not settings.resolve_media_path(doc["sources"][sid]["path"]).is_file():
            raise RenderError(f"“{doc['sources'][sid]['display_name']}” is missing.")


def render_frame(settings: Settings, doc: dict, t: float, out: Path, scale: float = 0.5) -> Path:
    """The exact-frame check: the frame at project time ``t`` from the real stage-1 segment (rendered if needed),
    with the project-wide overlays that show at that time."""
    timeline = resolve(doc, check_sources(settings, doc))
    scene, local = _scene_at(timeline, t)
    _check_media(doc, timeline, scene, settings)
    scratch = settings.scratch_dir / f"frame-{new_id('job')[4:]}"
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        segs, _, _ = ensure_segments(settings, doc, timeline, scratch, None, only={scene["id"]})
        rasters = RasterStore(settings.raster_dir)
        W, H = timeline["output"]["width"], timeline["output"]["height"]
        cmd = P.frame_from_segment(segs[0], local, out, timeline["overlays"], t, rasters.ensure,
                                   (max(2, int(W * scale) // 2 * 2), max(2, int(H * scale) // 2 * 2)))
        for ov in timeline["overlays"]:
            rasters.ensure(ov["raster"])
        run(cmd.args, label=cmd.label, timeout=120)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return out


def preview_clip(settings: Settings, doc: dict, scene_id: str, t0: float, t1: float, out: Path) -> Path:
    """A few seconds of one scene exactly as exported (video only), e.g. around a loop join."""
    timeline = resolve(doc, check_sources(settings, doc))
    scene = next((s for s in timeline["scenes"] if s["id"] == scene_id), None)
    if scene is None:
        raise RenderError("That scene isn't in the video.")
    _check_media(doc, timeline, scene, settings)
    scratch = settings.scratch_dir / f"clip-{new_id('job')[4:]}"
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        segs, _, _ = ensure_segments(settings, doc, timeline, scratch, None, only={scene_id})
        t0 = max(0.0, min(t0, scene["duration_s"] - 0.1))
        t1 = max(t0 + 0.1, min(t1, scene["duration_s"]))
        cmd = P.clip_from_segment(segs[0], t0, t1, out)
        run(cmd.args, label=cmd.label, timeout=300)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return out


def _prune_segment_cache(folder: Path, max_bytes: int = SEGMENT_CACHE_MAX_BYTES) -> None:
    try:
        files = sorted((p for p in folder.glob("*.mp4") if ".part." not in p.name), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for p in files:
            if total <= max_bytes:
                break
            total -= p.stat().st_size
            p.unlink(missing_ok=True)
    except OSError:
        log.debug("segment cache prune failed", exc_info=True)

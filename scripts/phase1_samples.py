"""Render the Phase 1 sample videos from owned, FFmpeg-generated footage and verify each one.

    .venv\\Scripts\\python scripts\\phase1_samples.py

Output: test-output/phase-1/samples/ (MP4s, frames at the start/middle/end, ffprobe JSON, summary.json).
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from shorts_studio.config import Settings  # noqa: E402
from shorts_studio.db import Database  # noqa: E402
from shorts_studio.jobs import EventHub, JobManager  # noqa: E402
from shorts_studio.media import importer  # noqa: E402
from shorts_studio.project import presets  # noqa: E402
from shorts_studio.project.store import ProjectStore  # noqa: E402
from shorts_studio.render.engine import render_project  # noqa: E402
from shorts_studio.render.ffmpeg import CancelToken, probe_json, run  # noqa: E402
from shorts_studio.testmedia import bands_video  # noqa: E402

OUT = ROOT / "test-output" / "phase-1" / "samples"

SAMPLES = [
    # name, source key, trim, reframe mode, focus x, audio
    ("qs-13s-landscape-audio", "hd", (4.0, 17.0), "fill", 0.25, True),
    ("qs-13s-landscape-silent", "hd", (4.0, 17.0), "fill", 0.75, False),
    ("qs-13s-4k-hevc-blur-fill", "uhd", (2.0, 15.0), "blur_fill", 0.5, True),
    ("qs-15s-cap-fit", "hd", (0.0, 15.0), "fit", 0.5, True),
]


def frames(video: Path, duration: float, dest: Path) -> list[str]:
    """First frame, middle frame and the very last frame (decode the final half second, keep the last image)."""
    out = []
    for label, args in (("start", ["-ss", "0", "-i", str(video), "-frames:v", "1"]),
                        ("middle", ["-ss", f"{duration / 2:.3f}", "-i", str(video), "-frames:v", "1"]),
                        ("end", ["-ss", f"{max(0.0, duration - 0.5):.3f}", "-i", str(video), "-update", "1"])):
        png = dest / f"{video.stem}-{label}.png"
        run([*args, "-vf", "scale=540:960", str(png)], label="frame")
        if not png.is_file():
            raise RuntimeError(f"no {label} frame extracted from {video.name}")
        out.append(str(png))
    return out


def main() -> dict:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "frames").mkdir(parents=True)
    settings = Settings(data_dir=OUT / "data")
    settings.ensure_dirs()
    db = Database(settings.db_path)
    jobs = JobManager(db, EventHub())
    store = ProjectStore(settings.projects_dir)
    t0 = time.time()
    media = {
        "hd": bands_video(OUT / "media" / "landscape-1080p-h264-30s.mp4", seconds=30),
        "uhd": bands_video(OUT / "media" / "landscape-2160p-hevc-20s.mp4", seconds=20, size=(3840, 2160),
                           codec="libx265"),
    }
    print(f"test media made in {time.time() - t0:.1f}s")
    imported = {k: importer.probe_paths(settings, db, jobs, [str(p)])[0][0] for k, p in media.items()}

    summary: dict = {"samples": []}
    for name, key, (a, b), mode, fx, audio in SAMPLES:
        sid, record = imported[key]
        doc = presets.quick_short([(sid, record)], title=name)
        scene = doc["scenes"][0]
        seg = doc["segments"][scene["layers"]["primary"]["segment_id"]]
        seg["in_s"], seg["out_s"] = a, b
        scene["layers"]["primary"]["reframe"].update(mode=mode, focus={"x": fx, "y": 0.5})
        scene["audio"]["primary"]["enabled"] = audio
        doc = store.create(doc)
        started = time.time()
        res = render_project(settings, db, doc, store.renders_dir(doc["id"]), job_id=f"job_{name}",
                             cancel=CancelToken(), progress=lambda p, s: None)
        final = OUT / f"{name}.mp4"
        shutil.copy2(res["path"], final)
        (OUT / f"{name}.ffprobe.json").write_text(json.dumps(probe_json(final, count_packets=True), indent=2),
                                                   encoding="utf-8")
        reopened = store.load(doc["id"]).doc
        s = res["verify"]["summary"]
        entry = {
            "name": name, "file": str(final), "source": media[key].name, "trim": [a, b], "framing": mode,
            "focus_x": fx, "original_audio": audio, "verify_ok": res["verify"]["ok"],
            "failed_checks": res["verify"]["failed"], "width": s.get("width"), "height": s.get("height"),
            "fps": s.get("fps"), "frames": s.get("frames"), "video_duration_s": s.get("video_duration_s"),
            "audio_streams": s.get("audio_streams"), "loudness_lufs": (s.get("loudness") or {}).get("integrated_lufs"),
            "true_peak_dbfs": (s.get("loudness") or {}).get("true_peak_dbfs"),
            "render_seconds": round(time.time() - started, 2),
            "reopened_matches_saved": reopened == doc,
            "frames_png": frames(final, s.get("video_duration_s") or (b - a), OUT / "frames"),
        }
        summary["samples"].append(entry)
        print(f"{name}: ok={entry['verify_ok']} {entry['width']}x{entry['height']} {entry['fps']}fps "
              f"{entry['frames']}f {entry['video_duration_s']}s audio={entry['audio_streams']} "
              f"lufs={entry['loudness_lufs']} in {entry['render_seconds']}s")

    # The 4K HEVC source needs a browser preview copy; wait for the background job to make it.
    uhd_id = imported["uhd"][0]
    deadline = time.time() + 300
    row = db.get_media(uhd_id)
    while row["proxy_state"] not in ("ready", "failed") and time.time() < deadline:
        time.sleep(1)
        row = db.get_media(uhd_id)
    proxy = {"state": row["proxy_state"]}
    if row["proxy"]:
        info = probe_json(row["proxy"])
        v = next(x for x in info["streams"] if x["codec_type"] == "video")
        proxy.update(path=row["proxy"], codec=v["codec_name"], width=v["width"], height=v["height"])
    summary["uhd_preview_proxy"] = proxy
    print("4K HEVC preview proxy:", proxy)
    jobs.shutdown()
    summary["ok"] = all(e["verify_ok"] and e["reopened_matches_saved"] for e in summary["samples"]) \
        and proxy.get("state") == "ready"
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print("PASS" if main()["ok"] else "FAIL")

"""Render the Phase 2 sample videos from FFmpeg-generated footage, the offline Windows voice and generated music,
and verify each one.

    .venv\\Scripts\\python scripts\\phase2_samples.py

Output: test-output/phase-2/samples/ (MP4s, ffprobe JSON, the frames either side of every scene boundary, a contact
sheet per sample, summary.json).
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from shorts_studio.config import Settings  # noqa: E402
from shorts_studio.db import Database  # noqa: E402
from shorts_studio.jobs import EventHub, JobManager  # noqa: E402
from shorts_studio.media import gameplay, importer, samples  # noqa: E402
from shorts_studio.project import presets  # noqa: E402
from shorts_studio.project.store import ProjectStore  # noqa: E402
from shorts_studio.render.engine import render_project  # noqa: E402
from shorts_studio.render.ffmpeg import CancelToken, probe_json  # noqa: E402
from shorts_studio.speech import takes  # noqa: E402
from shorts_studio.testmedia import bands_video, solid_video  # noqa: E402
from shorts_studio.timeline.resolve import resolve, take_state  # noqa: E402

OUT = ROOT / "test-output" / "phase-2" / "samples"
SYSTEM_VOICE = {"provider": "system", "voice_id": "", "rate_pct": 0}


class Studio:
    def __init__(self) -> None:
        self.settings = Settings(data_dir=OUT / "data")
        self.settings.ensure_dirs()
        self.db = Database(self.settings.db_path)
        self.jobs = JobManager(self.db, EventHub())
        self.store = ProjectStore(self.settings.projects_dir)

    def imp(self, *paths: Path) -> list[tuple[str, dict]]:
        sources, errors = importer.probe_paths(self.settings, self.db, self.jobs, [str(p) for p in paths])
        assert not errors, errors
        return sources

    def voice(self, doc: dict) -> dict:
        for s in doc["scenes"]:
            n = s.get("narration")
            if n and n["text"] and take_state(doc, s) != "ready":
                v = n.get("voice") or doc["voice"]
                n["take"] = takes.generate(self.settings, n["text"], v["provider"], v["voice_id"], v["rate_pct"])
        return doc

    def music(self, doc: dict, gain: float = -16) -> None:
        f = samples.music_loop(self.settings.music_dir / samples.MUSIC_NAME) \
            if not (self.settings.music_dir / samples.MUSIC_NAME).is_file() else self.settings.music_dir / samples.MUSIC_NAME
        (sid, rec), = self.imp(f)
        rec["origin"] = "generated"
        rec["display_name"] = "Generated sample music loop (royalty-free)"
        doc["sources"][sid] = rec
        doc["audio"]["music"] = {"source_id": sid, "enabled": True, "gain_db": gain, "start_offset_s": 0,
                                 "fade_in_s": 0.4, "fade_out_s": 0.8, "loop": True}

    def pick(self, clip_id: str, seconds: float, seed: int) -> dict:
        return gameplay.pick(self.settings, self.db, clip_id, seconds, project_id=None, scene_id=None, seed=seed)

    def render(self, doc: dict) -> dict:
        importer.ensure_registered(self.settings, self.db, self.jobs, doc)
        return render_project(self.settings, self.db, doc, self.store.renders_dir(doc["id"]),
                              job_id=f"job_{time.time_ns()}", cancel=CancelToken(), progress=lambda p, s: None)


def boundary_frames(video: Path, timeline: dict, dest: Path) -> list[str]:
    """The last frame of each scene and the first of the next (plus the very first and last), as PNGs."""
    total = timeline["frames"]
    picks = {0, total - 1}
    for s in timeline["scenes"][1:]:
        picks |= {s["start_frame"] - 1, s["start_frame"]}
    picks = sorted(picks)
    tmp = dest / f"{video.stem}-%02d.png"
    expr = "+".join(f"eq(n\\,{n})" for n in picks)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", f"select='{expr}',scale=270:480",
                    "-fps_mode", "passthrough", str(tmp)], check=True)
    out = []
    for k, n in enumerate(picks, 1):
        src = dest / f"{video.stem}-{k:02d}.png"
        final = dest / f"{video.stem}-frame{n:04d}.png"
        src.replace(final)
        out.append(str(final))
    sheet = dest.parent / f"{video.stem}-boundaries.png"
    inputs = []
    for f in out:
        inputs += ["-i", f]
    cols = len(out)
    layout = "|".join(f"{270 * i}_0" for i in range(cols))
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex",
                    f"{''.join(f'[{i}]' for i in range(cols))}xstack=inputs={cols}:layout={layout}", str(sheet)],
                   check=True)
    return out


def record(studio: Studio, name: str, doc: dict, res: dict, notes: dict) -> dict:
    final = OUT / f"{name}.mp4"
    shutil.copy2(res["path"], final)
    info = probe_json(final, count_packets=True)
    (OUT / f"{name}.ffprobe.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    tl = resolve(doc)
    v = res["verify"]
    s = v["summary"]
    loud = s.get("loudness") or {}
    entry = {
        "name": name, "file": str(final), "verify_ok": v["ok"], "failed_checks": v["failed"],
        "width": s.get("width"), "height": s.get("height"), "fps": s.get("fps"), "frames": s.get("frames"),
        "timeline_frames": tl["frames"], "video_duration_s": s.get("video_duration_s"),
        "audio_streams": s.get("audio_streams"), "integrated_lufs": loud.get("integrated_lufs"),
        "true_peak_dbfs": loud.get("true_peak_dbfs"), "cache_hits": v.get("cache_hits"),
        "render_seconds": v.get("render_seconds"),
        "scenes": [{"name": x["name"], "rank": x["rank"], "start_frame": x["start_frame"], "frames": x["frames"],
                    "layout": x["layout"]["type"], "sounds": [a["track"] for a in x["audio"]],
                    "overlays": sorted({o["kind"] for o in x["overlays"]})} for x in tl["scenes"]],
        "music": bool(tl["music"]),
        "warnings": [i["message"] for i in tl["issues"]],
        "boundary_frames": boundary_frames(final, tl, OUT / "frames"),
        **notes,
    }
    print(f"{name}: ok={entry['verify_ok']} {entry['width']}x{entry['height']}@{entry['fps']} {entry['frames']}f "
          f"audio={entry['audio_streams']} lufs={entry['integrated_lufs']} tp={entry['true_peak_dbfs']} "
          f"hits={entry['cache_hits']} {json.dumps(notes)}")
    return entry


def main() -> dict:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "frames").mkdir(parents=True)
    st = Studio()
    m = OUT / "media"
    t0 = time.time()
    media = {
        "red": solid_video(m / "entry-red.mp4", "0xE53935", seconds=4, tone_hz=None),
        "green": solid_video(m / "entry-green.mp4", "0x43A047", seconds=4, tone_hz=None),
        "blue": solid_video(m / "entry-blue.mp4", "0x1E88E5", seconds=4, tone_hz=None),
        "rocket": bands_video(m / "fail-rocket.mp4", seconds=5),
        "ladder": solid_video(m / "fail-ladder.mp4", "0x8E24AA", seconds=5, tone_hz=220),
        "boss": solid_video(m / "fail-boss.mp4", "0x00897B", seconds=6, tone_hz=550),
        "talk": bands_video(m / "talking-10s.mp4", seconds=10),
        "gp4": bands_video(m / "gameplay-4s.mp4", seconds=4, audio=True),
    }
    gp_sample = gameplay.add_sample(st.settings, st.db, st.jobs)
    gp_short = gameplay.add(st.settings, st.db, st.jobs, [str(media["gp4"])], ["test"])[0][0]
    print(f"media made in {time.time() - t0:.1f}s")
    summary: dict = {"samples": [], "gameplay_library": [c["display_name"] for c in st.db.list_clips()]}

    # 1. Silent countdown, reordered after creation (red moves from #3 to #1).
    doc = presets.ranking(st.imp(media["red"], media["green"], media["blue"]), title="Silent countdown")
    doc["overlays"]["title_bar"] = presets.d.title_bar("3 colours, ranked")
    doc["scenes"].append(doc["scenes"].pop(0))
    doc = st.store.create(doc)
    res = st.render(doc)
    summary["samples"].append(record(st, "silent-countdown-reordered", doc, res,
                                     {"order_after_drag": [s["name"] for s in doc["scenes"]]}))

    # 2. Narrated explainer; line 2 edited and only its take regenerated.
    doc = presets.story("Vancouver gets rain on about 160 days a year. But most of it is light drizzle. "
                        "So pack a light rain jacket, not an umbrella.", title="Rain in Vancouver", country="CA")
    doc["voice"] = dict(SYSTEM_VOICE)
    st.music(doc, gain=-18)
    doc = st.store.create(st.voice(doc))
    first = st.render(doc)
    takes_before = [s["narration"]["take"]["id"] for s in doc["scenes"]]
    frames_before = [s["frames"] for s in resolve(doc)["scenes"]]
    doc["scenes"][1]["narration"]["text"] = "But most of it is a light, misty drizzle that barely needs an umbrella."
    doc = st.store.save(doc["id"], st.voice(doc), doc["revision"])
    res = st.render(doc)
    takes_after = [s["narration"]["take"]["id"] for s in doc["scenes"]]
    summary["samples"].append(record(st, "narrated-explainer-line-edited", doc, res, {
        "takes_unchanged": [a == b for a, b in zip(takes_before, takes_after)],
        "scene_frames_before_after": [frames_before, [s["frames"] for s in resolve(doc)["scenes"]]],
        "first_render_lufs": (first["verify"]["summary"].get("loudness") or {}).get("integrated_lufs")}))

    # 3. Split screen with looping, muted gameplay (a 4 s clip under a 10 s scene).
    pick = st.pick(gp_short["id"], 10.0, seed=1)
    doc = presets.clips_over_gameplay(st.imp(media["talk"]), pick, title="Split with looping gameplay")
    doc = st.store.create(doc)
    res = st.render(doc)
    joins = resolve(doc)["scenes"][0]["layers"][1]["loop"]["joins"]
    summary["samples"].append(record(st, "split-looping-muted-gameplay", doc, res,
                                     {"loop_joins_s": joins, "gameplay_sound": doc["scenes"][0]["audio"]["secondary"]}))

    # 4. Picture in picture over a stretch of the (60 s) sample gameplay.
    pick = st.pick(gp_sample["id"], 10.0, seed=2)
    doc = presets.clips_over_gameplay(st.imp(media["talk"]), pick, layout="pip", title="PiP over gameplay")
    doc = st.store.create(doc)
    res = st.render(doc)
    summary["samples"].append(record(st, "pip-over-gameplay", doc, res,
                                     {"gameplay_stretch_s": [pick["segment"]["in_s"], pick["segment"]["out_s"]]}))

    # 5. Mixed Top 3: #3 original sound, #2 narrated (its clip ducked), #1 above a gameplay split. Then edit only #1.
    doc = presets.ranking(st.imp(media["rocket"], media["ladder"], media["boss"]), title="Top 3 funniest gaming fails")
    doc["voice"] = dict(SYSTEM_VOICE)
    doc["overlays"]["title_bar"] = presets.d.title_bar("Top 3 funniest gaming fails")
    s3, s2, s1 = doc["scenes"]
    s2["narration"] = {"text": "Number two. He trusted the ladder. The ladder did not trust him.", "voice": None,
                       "offset_s": 0.2, "take": None}
    s2["audio"]["narration"]["enabled"] = True
    s2["audio"]["primary"].update(gain_db=-6, duck_under_narration=True)
    s2["audio"]["music"]["enabled"] = True
    s2["duration"] = {"driver": "narration", "fixed_s": None, "tail_pad_s": 0.3}
    s2["layers"]["primary"]["playback"]["when_short"] = "loop"
    doc["captions"]["enabled"] = True
    doc["captions"]["default_mode"] = "off"
    s2["captions"]["mode"] = "narration_words"
    st.music(doc)
    pick = st.pick(gp_sample["id"], 6.0, seed=3)
    doc["sources"][pick["source_id"]] = pick["source"]
    doc["segments"][pick["segment_id"]] = pick["segment"]
    presets._with_gameplay(s1, pick["segment_id"], "split")
    doc = st.store.create(st.voice(doc))
    res = st.render(doc)
    summary["samples"].append(record(st, "mixed-top3", doc, res, {}))
    before = copy.deepcopy(doc["scenes"][:2])
    doc["scenes"][2]["layout"]["split"]["divider"] = 0.62
    doc = st.store.save(doc["id"], doc, doc["revision"])
    reopened = st.store.load(doc["id"]).doc
    res2 = st.render(reopened)
    keys = [[s["cache_key"] for s in r["verify"]["scene_segments"]] for r in (res, res2)]
    summary["samples"].append(record(st, "mixed-top3-after-editing-1", reopened, res2, {
        "scenes_3_and_2_unchanged_in_document": reopened["scenes"][:2] == before,
        "segment_keys_same": [a == b for a, b in zip(*keys)]}))

    # 6. Reddit-style story over gameplay, with music under the voice and a text card outro.
    pick = st.pick(gp_sample["id"], 60.0, seed=4)
    doc = presets.story("I asked u/neighbor_guy to move his car out of my driveway. He said no. "
                        "So I parked my tractor right behind his car, and waited.",
                        reddit={"community": "r/pettyrevenge", "title": "My neighbor kept blocking my driveway",
                                "source_url": "https://www.reddit.com/r/pettyrevenge/"}, gameplay=pick,
                        title="Driveway revenge")
    doc["voice"] = dict(SYSTEM_VOICE)
    st.music(doc, gain=-18)
    outro = presets.blank()["scenes"][0]
    outro["layers"]["primary"]["text_card"]["text"] = "Would you have done the same?"
    doc["scenes"].append(outro)
    doc = st.store.create(st.voice(doc))
    res = st.render(doc)
    summary["samples"].append(record(st, "reddit-story-over-gameplay", doc, res, {
        "usernames_replaced": doc["extensions"]["import"]["usernames_replaced"],
        "first_line": doc["scenes"][1]["narration"]["text"]}))

    st.jobs.shutdown()
    summary["ok"] = all(e["verify_ok"] for e in summary["samples"])
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print("PASS" if main()["ok"] else "FAIL")

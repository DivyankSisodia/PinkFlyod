"""Phase 2 browser test. Drives the real UI in Microsoft Edge (headless) against a server with its own data folder:

  A. silent ranking: create from three silent clips, drag #3 to the end, ranks renumber, export has no audio track
  B. narrated explainer (offline system voice): voices for every line, edit line 2, regenerate only that take,
     later scenes move by the new length, captions follow the new words, export at -14 LUFS
  C. gameplay library + clips over gameplay: add a 4 s clip, split screen loops it, preview a loop join through the
     export pipeline, switch to picture in picture, export both
  D. mixed "Top 3": #3 keeps its sound, #2 gets a recorded-style voice line, #1 sits over gameplay; edit only #1,
     re-export, #3 and #2 are unchanged (same document, cached segments, same frames)

    .venv\\Scripts\\python scripts\\ui_e2e_p2.py [--headed]

Writes screenshots, exports, frames and report.json to test-output/phase-2/ui/.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from shorts_studio.render.ffmpeg import probe_json  # noqa: E402
from shorts_studio.testmedia import bands_video, solid_video  # noqa: E402

OUT = ROOT / "test-output" / "phase-2" / "ui"
PORT = 17871
BASE = f"http://127.0.0.1:{PORT}/"
COLOURS = {"red": (0xE5, 0x39, 0x35), "green": (0x43, 0xA0, 0x47), "blue": (0x1E, 0x88, 0xE5),
           "orange": (0xFB, 0x8C, 0x00), "purple": (0x8E, 0x24, 0xAA), "teal": (0x00, 0x89, 0x7B)}
TOKEN = ""


def wait_health(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + "api/health", timeout=1) as r:
                return json.loads(r.read())
        except OSError:
            time.sleep(0.25)
    raise RuntimeError("server did not start")


def api(path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(BASE + path.lstrip("/"), method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Studio-Token": TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def project_json(pid: str) -> dict:
    return json.loads((OUT / "data" / "projects" / pid / "project.json").read_text(encoding="utf-8"))


def nearest(rgb) -> str:
    return min(COLOURS, key=lambda k: sum((a - b) ** 2 for a, b in zip(COLOURS[k], rgb)))


def frame_rgb(video: Path, n: int, png: Path | None = None) -> bytes:
    """Frame ``n`` (0-based) as raw RGB 1080x1920, optionally saved as a PNG for inspection."""
    vf = f"select=eq(n\\,{n})"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", vf, "-vframes", "1", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    if png:
        png.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", f"{vf},scale=540:960", "-vframes", "1",
                        str(png)], check=True)
    assert len(raw) == 1080 * 1920 * 3, (video, n, len(raw))
    return raw


def px(raw: bytes, x: int, y: int) -> tuple[int, int, int]:
    i = (y * 1080 + x) * 3
    return raw[i], raw[i + 1], raw[i + 2]


def mean_abs_diff(a: bytes, b: bytes) -> float:
    step = 997                                   # a sparse sample is plenty to tell "same" from "different"
    idx = range(0, len(a), step)
    return sum(abs(a[i] - b[i]) for i in idx) / len(idx)


def canvas_pixel(page, x, y):
    return page.evaluate(
        """([x, y]) => { const c = document.querySelector('[data-testid=preview-canvas]');
             const d = c.getContext('2d').getImageData(x, y, 1, 1).data; return [d[0], d[1], d[2]] }""", [x, y])


def wait_until(fn, timeout=20, what="condition"):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {what} (last: {last})")


def saved(page):
    expect(page.get_by_test_id("save-state")).to_have_text("Saved", timeout=15_000)


def export(page, name: str) -> tuple[Path, list[str]]:
    page.get_by_test_id("export").click()
    expect(page.get_by_test_id("export-dialog")).to_be_visible()
    page.get_by_test_id("start-export").click()
    expect(page.get_by_test_id("export-done")).to_be_visible(timeout=300_000)
    facts = page.get_by_test_id("export-facts").inner_text().splitlines()
    rendered = Path(page.locator(".done .path").inner_text())
    page.screenshot(path=OUT / "screens" / f"{name}-export.png")
    page.get_by_role("button", name="Close").first.click()
    dest = OUT / f"{name}.mp4"
    shutil.copy2(rendered, dest)
    return dest, facts


def probe(path: Path) -> dict:
    info = probe_json(path, count_packets=True)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    return {"width": v["width"], "height": v["height"], "fps": v["avg_frame_rate"], "frames": int(v["nb_read_packets"]),
            "duration_s": float(info["format"]["duration"]),
            "audio": [s["codec_name"] for s in info["streams"] if s["codec_type"] == "audio"]}


def lufs(facts: list[str]) -> float | None:
    m = next((re.search(r"(-?\d+(\.\d+)?) LUFS", f) for f in facts if "LUFS" in f), None)
    return float(m.group(1)) if m else None


def card_ranks(page) -> list[str]:
    return [c.inner_text() for c in page.get_by_test_id("card-rank").all()]


def open_editor_from_files(page, preset: str, files: list[Path]) -> str:
    page.goto(BASE)
    page.get_by_test_id(f"preset-{preset}").click()
    page.get_by_test_id("file-input").set_input_files([str(f) for f in files])
    page.wait_for_url("**/#/p/prj_*", timeout=60_000)
    expect(page.get_by_test_id("preview-canvas")).to_be_visible()
    return page.url.split("#/p/")[1]


def main(headed: bool = False) -> dict:
    global TOKEN
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "screens").mkdir(parents=True)
    (OUT / "frames").mkdir(parents=True)
    m = OUT / "media"
    silent = {c: solid_video(m / f"entry-{c}.mp4", f"0x{bytes(COLOURS[c]).hex()}", seconds=4, tone_hz=None)
              for c in ("red", "green", "blue")}
    top3 = {name: solid_video(m / f"fail-{name}.mp4", f"0x{bytes(COLOURS[c]).hex()}", seconds=4, tone_hz=hz)
            for name, c, hz in (("rocket", "orange", 330), ("ladder", "purple", 220), ("boss", "teal", 550))}
    gp_clip = bands_video(m / "gameplay-4s.mp4", seconds=4)
    top_clip = solid_video(m / "talking-red-10s.mp4", f"0x{bytes(COLOURS['red']).hex()}", seconds=10, tone_hz=440)

    env = {**os.environ, "SHORTS_STUDIO_DATA": str(OUT / "data"), "SHORTS_STUDIO_PORT": str(PORT)}
    server = subprocess.Popen([sys.executable, "-m", "shorts_studio", "--no-browser"], env=env, cwd=ROOT,
                              stdout=open(OUT / "server.log", "w"), stderr=subprocess.STDOUT)
    report: dict = {"steps": []}

    def step(name, **facts):
        report["steps"].append({"step": name, **facts})
        print(f"ok  {name} {json.dumps(facts, default=str) if facts else ''}")

    try:
        report["health"] = wait_health()
        TOKEN = api("api/session")["token"]
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=not headed)
            page = browser.new_page(viewport={"width": 1500, "height": 960})
            console: list[str] = []
            page.on("console", lambda msg: console.append(f"{msg.type}: {msg.text}"))
            page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
            failed: list[str] = []
            page.on("response", lambda r: r.status >= 400 and failed.append(f"{r.status} {r.url}"))

            # ── A. silent ranking, reordered ────────────────────────────────────────
            pid_a = open_editor_from_files(page, "ranking", [silent["red"], silent["green"], silent["blue"]])
            expect(page.get_by_test_id("card-rank")).to_have_count(3)
            assert card_ranks(page) == ["#3", "#2", "#1"], card_ranks(page)
            first_ids = [c.get_attribute("data-scene-id") for c in page.get_by_test_id("scene-card").all()]
            wait_until(lambda: "badge" in page.evaluate("window.__preview?.overlays ?? []"), what="badge in preview")
            page.screenshot(path=OUT / "screens" / "A1-ranking.png")
            step("A ranking: three entries numbered #3 #2 #1, badge drawn in the preview")
            cards = page.get_by_test_id("scene-card")
            box = cards.nth(2).bounding_box()
            cards.nth(0).drag_to(cards.nth(2), target_position={"x": box["width"] - 8, "y": box["height"] / 2})
            wait_until(lambda: [c.get_attribute("data-scene-id") for c in page.get_by_test_id("scene-card").all()]
                       == [first_ids[1], first_ids[2], first_ids[0]], what="red entry dragged to the end")
            assert card_ranks(page) == ["#3", "#2", "#1"], card_ranks(page)
            expect(page.get_by_test_id("scene-card").nth(2)).to_contain_text("#13. Entry red")
            saved(page)
            doc_a = project_json(pid_a)
            assert [s["id"] for s in doc_a["scenes"]] == [first_ids[1], first_ids[2], first_ids[0]]
            page.screenshot(path=OUT / "screens" / "A2-reordered.png")
            step("A drag: red moved from #3 to the end and is now #1; numbers follow the order")
            a_mp4, a_facts = export(page, "A-silent-ranking-reordered")
            a_probe = probe(a_mp4)
            assert "No audio track" in a_facts, a_facts
            assert a_probe["audio"] == [] and a_probe["frames"] == 360 and (a_probe["width"], a_probe["height"]) == (1080, 1920)
            order = []
            for n in (0, 119, 120, 239, 240, 359):
                raw = frame_rgb(a_mp4, n, OUT / "frames" / f"A-frame-{n:03d}.png")
                order.append(nearest(px(raw, 540, 1150)))
            assert order == ["green", "green", "blue", "blue", "red", "red"], order
            step("A export: silent (no audio stream), 360 frames, boundaries exact", probe=a_probe,
                 boundary_colours=dict(zip([0, 119, 120, 239, 240, 359], order)))

            # ── B. narrated explainer, one line regenerated ──────────────────────────
            page.goto(BASE)
            page.get_by_test_id("scratch-script").click()
            page.get_by_test_id("scratch-text").fill(
                "Octopuses have three hearts and blue blood. Two hearts pump blood to the gills. "
                "The third heart stops when they swim, so they prefer crawling.")
            page.get_by_test_id("scratch-voice").select_option("system")
            page.get_by_test_id("scratch-title").fill("Octopus facts")
            page.get_by_test_id("create-scratch").click()
            page.wait_for_url("**/#/p/prj_*", timeout=60_000)
            pid_b = page.url.split("#/p/")[1]
            expect(page.get_by_test_id("scene-card")).to_have_count(3)
            page.get_by_test_id("generate-all").click()
            expect(page.locator(".tag.take.ready")).to_have_count(3, timeout=180_000)
            saved(page)
            doc_b1 = project_json(pid_b)
            tl_b1 = api("api/resolve", {"project": doc_b1})
            takes1 = [s["narration"]["take"]["id"] for s in doc_b1["scenes"]]
            step("B voices: three lines voiced offline with the system voice",
                 durations=[s["narration"]["take"]["duration_s"] for s in doc_b1["scenes"]])
            page.get_by_test_id("scene-card").nth(1).click()
            new_line = "Two of the hearts only pump blood through the gills, and they work all day long."
            box_text = page.get_by_test_id("narration-text")
            box_text.fill(new_line)
            box_text.blur()
            expect(page.get_by_test_id("take-state")).to_have_text("Line changed: regenerate", timeout=10_000)
            page.screenshot(path=OUT / "screens" / "B1-line-stale.png")
            page.get_by_test_id("generate-take").click()
            expect(page.get_by_test_id("take-state")).to_have_text("Voice ready", timeout=120_000)
            saved(page)
            doc_b2 = project_json(pid_b)
            tl_b2 = api("api/resolve", {"project": doc_b2})
            takes2 = [s["narration"]["take"]["id"] for s in doc_b2["scenes"]]
            assert takes2[0] == takes1[0] and takes2[2] == takes1[2] and takes2[1] != takes1[1], (takes1, takes2)
            assert doc_b2["scenes"][0] == doc_b1["scenes"][0] and doc_b2["scenes"][2] == doc_b1["scenes"][2]
            s1, s2, s3 = tl_b2["scenes"]
            assert s3["start_frame"] == s1["frames"] + s2["frames"]
            shift = (s3["start_frame"] - tl_b1["scenes"][2]["start_frame"]) / 30
            spoken = [w[0].strip(".,").lower() for w in s2["narration"]["words"]]
            assert spoken == [w.strip(".,").lower() for w in new_line.split()], spoken
            assert s2["narration"]["words"][-1][1] < s2["narration"]["duration_s"], s2["narration"]["words"][-1]
            caps = [o for o in s2["overlays"] if o["kind"] == "caption"]
            assert caps and all(0 <= o["start_s"] < o["end_s"] <= s2["duration_s"] + 1e-6 for o in caps)
            page.screenshot(path=OUT / "screens" / "B2-line-regenerated.png")
            step("B edit: only line 2's take was redone; lines 1 and 3 untouched; line 3 moved with the new length",
                 line3_shift_s=round(shift, 3), captions_for_line2=len(caps))
            b_mp4, b_facts = export(page, "B-narrated-explainer-line-edited")
            b_probe = probe(b_mp4)
            b_lufs = lufs(b_facts)
            assert b_probe["audio"] == ["aac"] and b_lufs is not None and abs(b_lufs + 14) <= 1.0, (b_facts, b_probe)
            assert b_probe["frames"] == tl_b2["frames"]
            for n, label in ((s2["start_frame"] + 15, "B-line2"), (s3["start_frame"] + 15, "B-line3")):
                frame_rgb(b_mp4, n, OUT / "frames" / f"{label}-frame-{n:03d}.png")
            step("B export: narrated, captions burned in", probe=b_probe, lufs=b_lufs)

            # ── C. gameplay library, split with a loop, join preview, PiP ───────────────
            page.goto(BASE + "#/library/gameplay")
            page.route("**/api/dialog", lambda route: route.fulfill(json={"paths": [str(gp_clip)]}))
            page.get_by_role("textbox", name="Tags for new clips").fill("test, bands")
            page.get_by_test_id("gameplay-add").click()
            expect(page.get_by_test_id("gameplay-clip")).to_have_count(1, timeout=30_000)
            page.unroute("**/api/dialog")
            page.get_by_test_id("gameplay-sample").click()
            expect(page.get_by_test_id("gameplay-clip")).to_have_count(2, timeout=300_000)
            page.screenshot(path=OUT / "screens" / "C1-library.png")
            clips = api("api/gameplay")["clips"]
            own = next(c for c in clips if not c["sample"])
            assert own["tags"] == ["bands", "test"], own["tags"]
            step("C library: own 4 s clip added with tags, sample clip generated", clips=[c["display_name"] for c in clips])
            page.goto(BASE)
            page.get_by_test_id("preset-gameplay").click()
            page.get_by_test_id("home-gameplay").select_option(own["id"])
            page.get_by_test_id("home-gp-layout").select_option("split")
            page.get_by_test_id("file-input").set_input_files(str(top_clip))
            page.wait_for_url("**/#/p/prj_*", timeout=60_000)
            pid_c = page.url.split("#/p/")[1]
            page.get_by_test_id("layer-secondary").click()
            expect(page.get_by_test_id("joins")).to_be_visible(timeout=15_000)
            joins_text = page.get_by_test_id("joins").inner_text()
            expect(page.get_by_test_id("secondary-audio-toggle")).not_to_be_checked()
            wait_until(lambda: nearest(canvas_pixel(page, 270, 240)) == "red", what="top half shows the clip")
            low = canvas_pixel(page, 270, 720)
            assert nearest(low) != "red", low
            page.screenshot(path=OUT / "screens" / "C2-split.png")
            page.get_by_test_id("preview-join").first.click()
            expect(page.get_by_test_id("join-preview")).to_be_visible(timeout=120_000)
            dur = wait_until(lambda: page.evaluate(
                "(() => { const v = document.querySelector('.join-video'); return v && v.readyState >= 1 ? v.duration : 0 })()"),
                what="join clip loaded")
            page.screenshot(path=OUT / "screens" / "C3-join-preview.png")
            page.get_by_test_id("join-close").click()
            step("C split: gameplay below loops (muted), join previewed through the export pipeline",
                 joins=joins_text.splitlines()[0], join_clip_s=round(dur, 2))
            saved(page)
            c_mp4, c_facts = export(page, "C-split-looping-muted-gameplay")
            c_probe = probe(c_mp4)
            c_lufs = lufs(c_facts)
            assert c_probe["frames"] == 300 and c_probe["audio"] == ["aac"] and abs(c_lufs + 14) <= 1.0, (c_probe, c_facts)
            tl_c = api("api/resolve", {"project": project_json(pid_c)})
            joins = tl_c["scenes"][0]["layers"][1]["loop"]["joins"]
            for k, j in enumerate(joins):
                n = round(j * 30)
                for d_n in (-1, 0, 1):
                    raw = frame_rgb(c_mp4, n + d_n, OUT / "frames" / f"C-join{k}-frame-{n + d_n:03d}.png")
                    assert nearest(px(raw, 540, 400)) == "red"
            sec_audio = [a["track"] for a in tl_c["scenes"][0]["audio"]]
            assert sec_audio == ["primary"], sec_audio
            step("C export: 10 s, top clip's sound only, frames around each join extracted", probe=c_probe,
                 lufs=c_lufs, joins_s=joins)
            page.get_by_test_id("layout-pip").click()
            page.get_by_test_id("pip-size").fill("0.6")
            saved(page)
            doc_c2 = project_json(pid_c)
            assert doc_c2["scenes"][0]["layout"]["type"] == "pip" and doc_c2["scenes"][0]["layout"]["pip"]["width"] == 0.6
            tl_c2 = api("api/resolve", {"project": doc_c2})
            inset = next(l for l in tl_c2["scenes"][0]["layers"] if l["pip"])["rect"]
            cx, cy = (inset["x"] + inset["w"] // 2) // 2, (inset["y"] + inset["h"] // 2) // 2
            wait_until(lambda: nearest(canvas_pixel(page, cx, cy)) == "red", what="PiP inset shows the clip")
            assert nearest(canvas_pixel(page, 270, 800)) != "red"
            page.screenshot(path=OUT / "screens" / "C4-pip.png")
            c2_mp4, c2_facts = export(page, "C-pip-gameplay")
            raw = frame_rgb(c2_mp4, 30, OUT / "frames" / "C-pip-frame-030.png")
            assert nearest(px(raw, inset["x"] + inset["w"] // 2, inset["y"] + inset["h"] // 2)) == "red"
            assert nearest(px(raw, 540, 1600)) != "red"
            step("C PiP: inset at 60 % width in the preview and the export", inset=inset, probe=probe(c2_mp4))

            # ── D. mixed Top 3; edit only #1 and re-export ────────────────────────────
            pid_d = open_editor_from_files(page, "ranking", [top3["rocket"], top3["ladder"], top3["boss"]])
            assert card_ranks(page) == ["#3", "#2", "#1"]
            cards = page.get_by_test_id("scene-card")
            cards.nth(0).click()
            expect(page.get_by_test_id("audio-toggle")).to_be_checked()
            cards.nth(1).click()
            page.get_by_test_id("add-narration").click()
            line = page.get_by_test_id("narration-text")
            line.fill("Number two. The ladder gives way at the worst moment.")
            line.blur()
            page.get_by_test_id("voice-provider").select_option("system")
            page.get_by_test_id("primary-duck").check()
            page.get_by_test_id("generate-take").click()
            expect(page.get_by_test_id("take-state")).to_have_text("Voice ready", timeout=120_000)
            cards.nth(2).click()
            page.get_by_test_id("add-gameplay").click()
            expect(page.get_by_test_id("gameplay-picker")).to_be_visible()
            page.get_by_test_id("gp-layout-split").click()
            page.get_by_test_id("gameplay-clip").filter(has_text="gameplay-4s").get_by_test_id("gameplay-use").click()
            expect(page.get_by_test_id("gameplay-picker")).to_be_hidden(timeout=15_000)
            page.get_by_test_id("sample-music").click()
            expect(page.get_by_test_id("music-gain")).to_be_visible(timeout=60_000)
            saved(page)
            page.screenshot(path=OUT / "screens" / "D1-mixed-top3.png")
            doc_d1 = project_json(pid_d)
            sc = doc_d1["scenes"]
            assert sc[0]["audio"]["primary"]["enabled"] and sc[0]["narration"] is None and sc[0]["layers"]["secondary"] is None
            assert sc[1]["narration"]["take"] and sc[1]["audio"]["primary"]["duck_under_narration"]
            assert sc[2]["layout"]["type"] == "split" and sc[2]["layers"]["secondary"]["type"] == "segment"
            step("D build: #3 original sound, #2 voiced and ducked, #1 over a gameplay split, music added")
            d1_mp4, d1_facts = export(page, "D-mixed-top3")
            d1_lufs = lufs(d1_facts)
            assert abs(d1_lufs + 14) <= 1.0, d1_facts
            cards.nth(2).click()
            page.get_by_test_id("divider").fill("0.62")
            saved(page)
            doc_d2 = project_json(pid_d)
            assert doc_d2["scenes"][0] == doc_d1["scenes"][0] and doc_d2["scenes"][1] == doc_d1["scenes"][1]
            assert doc_d2["scenes"][2]["layout"]["split"]["divider"] == 0.62
            d2_mp4, d2_facts = export(page, "D-mixed-top3-after-editing-1")
            renders = api(f"api/projects/{pid_d}/renders")["renders"]
            hits = renders[0]["verify"].get("cache_hits")
            tl_d = api("api/resolve", {"project": doc_d2})
            mids = [s["start_frame"] + s["frames"] // 2 for s in tl_d["scenes"]]
            diffs = []
            for k, n in enumerate(mids):
                a = frame_rgb(d1_mp4, n, OUT / "frames" / f"D-before-scene{k}-frame-{n:03d}.png")
                b = frame_rgb(d2_mp4, n, OUT / "frames" / f"D-after-scene{k}-frame-{n:03d}.png")
                diffs.append(round(mean_abs_diff(a, b), 3))
            assert diffs[0] < 0.5 and diffs[1] < 0.5 and diffs[2] > 2, diffs
            assert hits is not None and hits >= 2, hits
            page.screenshot(path=OUT / "screens" / "D2-after-editing-1.png")
            step("D persistence: only #1 changed; #3 and #2 identical in the document and in the frames",
                 cache_hits=hits, mean_abs_frame_diff=diffs, lufs=[d1_lufs, lufs(d2_facts)])

            report["console_errors"] = [c for c in console if c.startswith(("error", "pageerror"))]
            report["console_warnings"] = [c for c in console if c.startswith("warning")]
            report["failed_requests"] = failed
            browser.close()
        report["ok"] = not report["console_errors"] and not report["failed_requests"]
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
        (OUT / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


if __name__ == "__main__":
    r = main(headed="--headed" in sys.argv)
    print("console errors:", r.get("console_errors"))
    print("failed requests:", r.get("failed_requests"))
    print("PASS" if r.get("ok") else "FAIL")

"""Phase 1 browser test: launch -> import landscape footage -> select 13 s -> vertical crop -> preview -> export
-> reopen. Drives the real UI in Microsoft Edge (headless) against a server with its own data folder.

    .venv\\Scripts\\python scripts\\ui_e2e.py [--headed]

Writes screenshots and the exported MP4 to test-output/phase-1/ui/.
"""
from __future__ import annotations

import json
import os
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
from shorts_studio.testmedia import band_at, bands_video, classify  # noqa: E402

OUT = ROOT / "test-output" / "phase-1" / "ui"
PORT = 17870
BASE = f"http://127.0.0.1:{PORT}/"


def wait_health(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + "api/health", timeout=1) as r:
                return json.loads(r.read())
        except OSError:
            time.sleep(0.25)
    raise RuntimeError("server did not start")


def canvas_pixel(page, x, y):
    return page.evaluate(
        """([x, y]) => { const c = document.querySelector('[data-testid=preview-canvas]');
             const d = c.getContext('2d').getImageData(x, y, 1, 1).data; return [d[0], d[1], d[2]] }""", [x, y])


def wait_canvas_colour(page, x, y, want, timeout=15):
    deadline = time.time() + timeout
    got = None
    while time.time() < deadline:
        got = classify(tuple(canvas_pixel(page, x, y)))
        if got == want:
            return got
        time.sleep(0.2)
    raise AssertionError(f"canvas pixel ({x},{y}) is {got}, expected {want}")


def main(headed: bool = False) -> dict:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "screens").mkdir(parents=True)
    media = bands_video(OUT / "media" / "landscape-1080p-30s.mp4", seconds=30)
    env = {**os.environ, "SHORTS_STUDIO_DATA": str(OUT / "data"), "SHORTS_STUDIO_PORT": str(PORT)}
    server = subprocess.Popen([sys.executable, "-m", "shorts_studio", "--no-browser"], env=env, cwd=ROOT,
                              stdout=open(OUT / "server.log", "w"), stderr=subprocess.STDOUT)
    report: dict = {"steps": []}

    def step(name, **facts):
        report["steps"].append({"step": name, **facts})
        print(f"ok  {name} {json.dumps(facts) if facts else ''}")

    try:
        report["health"] = wait_health()
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=not headed)
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            console = []
            page.on("console", lambda m: console.append(f"{m.type}: {m.text}"))
            page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
            failed_requests: list[str] = []
            page.on("response", lambda r: r.status >= 400 and failed_requests.append(f"{r.status} {r.url}"))

            page.goto(BASE)
            expect(page.get_by_role("heading", name="What do you want to make?")).to_be_visible()
            page.screenshot(path=OUT / "screens" / "1-home.png")
            step("launch: home screen shows the two ways to start")

            page.get_by_test_id("file-input").set_input_files(str(media))
            page.wait_for_url("**/#/p/prj_*", timeout=60_000)
            expect(page.get_by_test_id("preview-canvas")).to_be_visible()
            project_id = page.url.split("#/p/")[1]
            step("import: landscape file copied in, editor opened", project=project_id)

            # Trim to 4–17 s, testing the 15 s cap on the way.
            page.get_by_test_id("open-trim").click()
            expect(page.get_by_test_id("trim-bench")).to_be_visible()
            page.get_by_test_id("out-input").fill("25")
            expect(page.get_by_test_id("trim-length")).to_have_text("15.00 s of max 15 s")
            step("cap: dragging out to 25 s keeps the selection at 15 s")
            page.get_by_test_id("in-input").fill("4")
            page.get_by_test_id("out-input").fill("17")
            expect(page.get_by_test_id("trim-length")).to_have_text("13.00 s of max 15 s")
            page.screenshot(path=OUT / "screens" / "2-trim.png")
            page.get_by_test_id("trim-done").click()
            expect(page.get_by_test_id("trim-bench")).to_be_hidden()
            step("select: 4.000–17.000 s (13.00 s)")

            # Vertical crop: focus on the left quarter of the frame.
            page.get_by_test_id("focus-x").fill("0.25")
            expect(page.get_by_test_id("save-state")).to_have_text("Saved", timeout=10_000)
            want = band_at(0.25 * 1920)
            wait_canvas_colour(page, 270, 550, want)
            page.screenshot(path=OUT / "screens" / "3-editor-crop.png")
            step("crop + preview: canvas centre shows the source column at 25 %", colour=want)

            # Undo and redo the crop.
            page.get_by_test_id("undo").click()
            expect(page.get_by_test_id("focus-x")).to_have_value("0.5")
            page.get_by_test_id("redo").click()
            expect(page.get_by_test_id("focus-x")).to_have_value("0.25")
            expect(page.get_by_test_id("save-state")).to_have_text("Saved", timeout=10_000)
            step("undo/redo restores the crop")

            # Preview playback runs.
            page.get_by_test_id("play").click()
            page.wait_for_timeout(1500)
            page.get_by_test_id("play").click()
            t_text = page.locator(".player-controls .time").inner_text()
            assert not t_text.startswith("0:00.00"), t_text
            step("preview plays", at=t_text)

            # Exact-frame check from the export pipeline.
            page.get_by_test_id("exact-frame-button").click()
            expect(page.get_by_test_id("exact-frame")).to_be_visible(timeout=30_000)
            page.screenshot(path=OUT / "screens" / "4-exact-frame.png")
            page.get_by_role("button", name="Close").first.click()
            step("exact frame rendered through the export graph")

            # Export.
            page.get_by_test_id("export").click()
            expect(page.get_by_test_id("export-dialog")).to_be_visible()
            page.get_by_test_id("start-export").click()
            expect(page.get_by_test_id("progress")).to_be_visible(timeout=10_000)
            expect(page.get_by_test_id("export-done")).to_be_visible(timeout=180_000)
            facts = page.get_by_test_id("export-facts").inner_text()
            page.screenshot(path=OUT / "screens" / "5-export-done.png")
            assert "1080×1920 at 30 fps, 390 frames" in facts, facts
            render_path = Path(page.locator(".done .path").inner_text())
            step("export: render job finished and was verified", facts=facts.splitlines())
            page.get_by_role("button", name="Close").first.click()

            # Reopen: reload the page, then come back through the home screen.
            page.reload()
            expect(page.get_by_test_id("focus-x")).to_have_value("0.25", timeout=15_000)
            page.get_by_test_id("open-trim").click()
            expect(page.get_by_test_id("in-input")).to_have_value("4.000")
            expect(page.get_by_test_id("out-input")).to_have_value("17.000")
            page.keyboard.press("Escape")
            page.get_by_text("← Projects").click()
            expect(page.get_by_test_id("recent-item").first).to_contain_text("Landscape 1080p 30s")
            page.screenshot(path=OUT / "screens" / "6-home-recent.png")
            page.get_by_test_id("recent-item").first.click()
            expect(page.get_by_test_id("focus-x")).to_have_value("0.25", timeout=15_000)
            step("reopen: crop and trim survived a reload and a return from the home screen")

            # Move the source file away, reopen, relink it. The native dialog is answered by intercepting
            # /api/dialog (a person would pick the file in the OS dialog).
            imported = next((OUT / "data" / "media" / "imports").glob("*/landscape-1080p-30s.mp4"))
            moved = OUT / "moved-away" / "renamed-footage.mp4"
            moved.parent.mkdir(parents=True, exist_ok=True)
            page.goto(BASE)                       # leave the editor so no player holds the file open
            for _ in range(40):
                try:
                    imported.rename(moved)
                    break
                except PermissionError:
                    time.sleep(0.25)
            else:
                raise AssertionError("could not move the source file")
            page.goto(BASE + f"#/p/{project_id}")
            expect(page.get_by_test_id("missing-notice")).to_be_visible(timeout=15_000)
            expect(page.get_by_test_id("preview-missing")).to_be_visible(timeout=15_000)
            page.screenshot(path=OUT / "screens" / "7-missing-media.png")
            step("missing file detected on reopen", moved_to=str(moved))
            page.route("**/api/dialog", lambda route: route.fulfill(json={"paths": [str(moved)]}))
            page.get_by_test_id("relink").click()
            expect(page.get_by_test_id("media-message")).to_have_text("Relinked: same file, new location.",
                                                                     timeout=15_000)
            expect(page.get_by_test_id("missing-notice")).to_be_hidden(timeout=15_000)
            expect(page.get_by_test_id("preview-missing")).to_be_hidden(timeout=15_000)
            expect(page.get_by_test_id("save-state")).to_have_text("Saved", timeout=10_000)
            wait_canvas_colour(page, 270, 550, want)
            page.get_by_test_id("export").click()
            page.get_by_test_id("start-export").click()
            expect(page.get_by_test_id("export-done")).to_be_visible(timeout=180_000)
            relinked_render = Path(page.locator(".done .path").inner_text())
            page.get_by_role("button", name="Close").first.click()
            page.unroute("**/api/dialog")
            step("relink: picked the moved file, preview and export work again")

            # "Choose files…" links a file in place instead of copying it.
            page.goto(BASE)
            page.route("**/api/dialog", lambda route: route.fulfill(json={"paths": [str(media)]}))
            page.get_by_test_id("choose-files").click()
            page.wait_for_url(lambda u: "#/p/prj_" in u and project_id not in u, timeout=60_000)
            expect(page.get_by_test_id("preview-canvas")).to_be_visible()
            linked_id = page.url.split("#/p/")[1]
            page.unroute("**/api/dialog")
            linked = json.loads((OUT / "data" / "projects" / linked_id / "project.json").read_text(encoding="utf-8"))
            linked_path = next(iter(linked["sources"].values()))["path"]
            assert Path(linked_path) == media, linked_path
            step("choose files: the project references the original file in place", path=linked_path)

            report["console_errors"] = [c for c in console if c.startswith(("error", "pageerror"))]
            report["failed_requests"] = failed_requests
            browser.close()

        exported = OUT / "ui-quick-short-13s.mp4"
        shutil.copy2(render_path, exported)
        info = probe_json(exported, count_packets=True)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        a = [s for s in info["streams"] if s["codec_type"] == "audio"]
        report["export"] = {"path": str(exported), "width": v["width"], "height": v["height"],
                            "avg_frame_rate": v["avg_frame_rate"], "frames": int(v["nb_read_packets"]),
                            "duration_s": float(info["format"]["duration"]), "audio": [x["codec_name"] for x in a]}
        assert (v["width"], v["height"], v["avg_frame_rate"], int(v["nb_read_packets"])) == (1080, 1920, "30/1", 390)
        step("ffprobe on the exported file", **report["export"])
        shutil.copy2(relinked_render, OUT / "ui-quick-short-13s-after-relink.mp4")
        report["ok"] = True
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    r = main(headed="--headed" in sys.argv)
    print("console errors:", r.get("console_errors"))
    print("failed requests:", r.get("failed_requests"))
    print("PASS" if r.get("ok") else "FAIL")

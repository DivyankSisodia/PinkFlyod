"""Browser test for the Upload details window, against its own data folder. The OpenCode job is answered by
intercepting two API calls (the real generation is covered by the backend tests and a live run).

    .venv\\Scripts\\python scripts\\ui_e2e_upload.py [--headed]
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
from shorts_studio.testmedia import bands_video  # noqa: E402

OUT = ROOT / "test-output" / "upload-ui"
PORT = 17874
BASE = f"http://127.0.0.1:{PORT}/"
RESULT = {
    "titles": ["Colour Bars Gone Wild 🌈 #shorts", "Watch These Bars Move #shorts", "Test Pattern Magic #shorts"],
    "description": "Watch these colour bars race by!\nCould you look away?\n\n#colorbars #shorts",
    "tags": [{"text": "color bars", "searched": True}, {"text": "test pattern", "searched": True},
             {"text": "rainbow stripes", "searched": False}],
    "summary": "Colour bands sweep past a moving marker.",
    "searches": [{"query": "color bars", "geo": "US", "suggestions": ["color bars", "color bars 4k"]}],
    "trends": [{"geo": "US", "items": [{"query": "seth meyers", "traffic": "500+"}]}],
    "trends_used": [], "collected_at": "2026-11-27T07:00:00Z", "frames_used": 3, "model": "test-model",
}


def wait_health(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + "api/health", timeout=1):
                return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError("server did not start")


def main(headed=False) -> bool:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "screens").mkdir(parents=True)
    media = bands_video(OUT / "media" / "bands-6s.mp4", seconds=6)
    env = {**os.environ, "SHORTS_STUDIO_DATA": str(OUT / "data"), "SHORTS_STUDIO_PORT": str(PORT),
           "OPENCODE_GO_API_KEY": "test-key", "OPENCODE_GO_MODEL": "test-model"}
    server = subprocess.Popen([sys.executable, "-m", "shorts_studio", "--no-browser"], env=env, cwd=ROOT,
                              stdout=open(OUT / "server.log", "w"), stderr=subprocess.STDOUT)
    try:
        wait_health()
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=not headed)
            ctx = browser.new_context(viewport={"width": 1440, "height": 960})
            ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE.rstrip("/"))
            page = ctx.new_page()
            problems: list[str] = []
            page.on("console", lambda m: m.type == "error" and problems.append(m.text))
            page.on("pageerror", lambda e: problems.append(str(e)))
            page.route("**/publish-draft", lambda r: r.fulfill(json={"job_id": "job_fakeuploaddetails"}))
            page.route("**/api/jobs/job_fakeuploaddetails", lambda r: r.fulfill(json={
                "id": "job_fakeuploaddetails", "kind": "publish_draft", "project_id": None, "status": "done",
                "pct": 100, "stage": "Done", "error": None, "result": RESULT}))
            page.goto(BASE)
            page.get_by_test_id("file-input").set_input_files(str(media))
            page.wait_for_url("**/#/p/prj_*", timeout=60_000)
            pid = page.url.split("#/p/")[1]
            page.get_by_test_id("upload-details").click()
            expect(page.get_by_test_id("upload-dialog")).to_be_visible()
            page.get_by_test_id("generate-upload").click()
            expect(page.get_by_test_id("upload-title")).to_have_value(RESULT["titles"][0], timeout=15_000)
            expect(page.get_by_test_id("upload-tags")).to_have_value("color bars, test pattern, rainbow stripes")
            expect(page.get_by_test_id("upload-dialog")).to_contain_text("2 match real YouTube searches")
            page.get_by_test_id("title-option").nth(1).click()
            expect(page.get_by_test_id("upload-title")).to_have_value(RESULT["titles"][1])
            page.get_by_test_id("copy-tags").click()
            assert page.evaluate("navigator.clipboard.readText()") == "color bars, test pattern, rainbow stripes"
            page.get_by_test_id("upload-description").fill("My own description.\n\n#shorts")
            page.get_by_test_id("save-upload").click()
            expect(page.get_by_test_id("save-upload")).to_have_text("Saved with the project")
            page.get_by_text("What it was based on").click()
            page.screenshot(path=OUT / "screens" / "upload-details.png")
            expect(page.get_by_test_id("save-state")).to_have_text("Saved", timeout=10_000)
            doc = json.loads((OUT / "data" / "projects" / pid / "project.json").read_text(encoding="utf-8"))
            pm = doc["publish_meta"]
            assert pm["title_drafts"][0] == {**pm["title_drafts"][0], "text": RESULT["titles"][1], "kind": "editorial"}
            assert pm["description"] == "My own description.\n\n#shorts"
            assert pm["tags"] == ["color bars", "test pattern", "rainbow stripes"]
            print("ok  generated, picked the 2nd title, copied tags, edited and saved into the project")
            page.reload()
            page.get_by_test_id("upload-details").click()
            expect(page.get_by_test_id("upload-title")).to_have_value(RESULT["titles"][1])
            expect(page.get_by_test_id("upload-description")).to_have_value("My own description.\n\n#shorts")
            print("ok  the saved details come back after a reload")
            browser.close()
        print("console errors:", problems)
        return not problems
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    print("PASS" if main("--headed" in sys.argv) else "FAIL")

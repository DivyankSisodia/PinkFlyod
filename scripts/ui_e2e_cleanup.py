"""Browser test for the delete buttons, against its own data folder (never your real projects):
export twice -> the Export dialog lists both -> "Delete older, keep newest" -> delete the last one -> on the home
screen delete the project -> it's gone from the list and from disk.

    .venv\\Scripts\\python scripts\\ui_e2e_cleanup.py [--headed]
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

OUT = ROOT / "test-output" / "cleanup-ui"
PORT = 17873
BASE = f"http://127.0.0.1:{PORT}/"


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
    media = bands_video(OUT / "media" / "clip-8s.mp4", seconds=8)
    env = {**os.environ, "SHORTS_STUDIO_DATA": str(OUT / "data"), "SHORTS_STUDIO_PORT": str(PORT)}
    server = subprocess.Popen([sys.executable, "-m", "shorts_studio", "--no-browser"], env=env, cwd=ROOT,
                              stdout=open(OUT / "server.log", "w"), stderr=subprocess.STDOUT)
    try:
        wait_health()
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=not headed)
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            problems: list[str] = []
            page.on("console", lambda m: m.type == "error" and problems.append(m.text))
            page.on("pageerror", lambda e: problems.append(str(e)))
            page.on("dialog", lambda d: d.accept())                    # the "keep newest?" confirm()
            page.goto(BASE)
            page.get_by_test_id("file-input").set_input_files(str(media))
            page.wait_for_url("**/#/p/prj_*", timeout=60_000)
            pid = page.url.split("#/p/")[1]
            for _ in range(2):
                page.get_by_test_id("export").click()
                page.get_by_test_id("start-export").click()
                expect(page.get_by_test_id("export-done")).to_be_visible(timeout=180_000)
                page.get_by_role("button", name="Close").first.click()
            renders = OUT / "data" / "projects" / pid / "renders"
            assert len(list(renders.glob("*.mp4"))) == 2
            page.get_by_test_id("export").click()
            expect(page.get_by_test_id("export-row")).to_have_count(2, timeout=10_000)
            page.screenshot(path=OUT / "screens" / "1-two-exports.png")
            page.get_by_test_id("keep-latest").click()
            expect(page.get_by_test_id("export-row")).to_have_count(1, timeout=10_000)
            assert len(list(renders.glob("*.mp4"))) == 1
            print("ok  'Delete older, keep newest' left 1 export")
            page.get_by_test_id("delete-export").click()
            expect(page.get_by_test_id("previous-exports")).to_contain_text("Deleted one export", timeout=10_000)
            assert list(renders.glob("*.mp4")) == []
            print("ok  deleting the last export removed its file")
            page.get_by_role("button", name="Close").first.click()
            page.get_by_text("← Projects").click()
            card = page.get_by_test_id("recent-item")
            expect(card).to_have_count(1)
            card.hover()
            page.get_by_test_id("delete-project").click()
            expect(page.get_by_test_id("delete-dialog")).to_contain_text("This removes", timeout=10_000)
            page.screenshot(path=OUT / "screens" / "2-delete-project.png")
            page.get_by_test_id("confirm-delete").click()
            expect(page.get_by_test_id("deleted-message")).to_contain_text("Deleted", timeout=15_000)
            expect(page.get_by_test_id("recent-item")).to_have_count(0)
            assert not (OUT / "data" / "projects" / pid).exists()
            page.screenshot(path=OUT / "screens" / "3-deleted.png")
            print("ok  project deleted from the home screen and from disk")
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

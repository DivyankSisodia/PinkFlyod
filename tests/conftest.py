from __future__ import annotations

import copy
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from shorts_studio.config import REPO_ROOT, Settings
from shorts_studio.db import Database
from shorts_studio.jobs import EventHub, JobManager
from shorts_studio.media import importer
from shorts_studio.testmedia import bands_video

EXAMPLES = REPO_ROOT / "schema" / "examples"
HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg and ffprobe on PATH")


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def example():
    return lambda name: copy.deepcopy(load_example(name))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(data_dir=tmp_path / "data", port=17860)
    s.ensure_dirs()
    return s


@pytest.fixture
def db(settings: Settings) -> Database:
    return Database(settings.db_path)


@pytest.fixture
def jobs(db: Database):
    jm = JobManager(db, EventHub())
    yield jm
    jm.shutdown()


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("media")


@pytest.fixture(scope="session")
def landscape(media_dir: Path) -> Path:
    """30 s, 1920×1080, 30 fps, colour bands + timestamp strip + tone with beeps."""
    if not HAS_FFMPEG:
        pytest.skip("needs ffmpeg")
    return bands_video(media_dir / "landscape-30s.mp4", seconds=30)


@pytest.fixture(scope="session")
def landscape_silent(media_dir: Path) -> Path:
    if not HAS_FFMPEG:
        pytest.skip("needs ffmpeg")
    return bands_video(media_dir / "landscape-noaudio-8s.mp4", seconds=8, audio=False)


@pytest.fixture
def imported(settings, db, jobs):
    def _import(*paths: Path, ownership: str = "own"):
        sources, errors = importer.probe_paths(settings, db, jobs, [str(p) for p in paths], ownership=ownership)
        assert not errors, errors
        return sources
    return _import


def frame_rgb(video: Path, t: float, width: int = 1080, height: int = 1920) -> bytes:
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    assert len(out.stdout) == width * height * 3, len(out.stdout)
    return out.stdout


def pixel(frame: bytes, x: int, y: int, width: int = 1080) -> tuple[int, int, int]:
    i = (y * width + x) * 3
    return frame[i], frame[i + 1], frame[i + 2]


def wait_for_job(get_job, job_id: str, timeout: float = 240) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = get_job(job_id)
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s")

"""The Phase 2 HTTP API: create from scratch, voice takes, the gameplay library, overlays, effects, music and the
loop-join preview."""
from __future__ import annotations

import sys

import pytest
from conftest import needs_ffmpeg, wait_for_job
from fastapi.testclient import TestClient

from shorts_studio.app import create_app
from shorts_studio.testmedia import bands_video

TOKEN = "test-token"
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows system voice")


@pytest.fixture
def client(settings):
    app = create_app(settings, extra_hosts={"testserver"}, token=TOKEN)
    with TestClient(app) as c:
        c.headers["X-Studio-Token"] = TOKEN
        yield c


def job(client, job_id):
    return wait_for_job(lambda j: client.get(f"/api/jobs/{j}").json(), job_id)


def test_create_from_script_and_reddit(client):
    r = client.post("/api/projects/script", json={"kind": "script", "text": "First line is here today. Second line "
                                                  "follows it closely.", "country": "CA", "voice_provider": "system"})
    assert r.status_code == 200, r.text
    doc = r.json()["project"]
    assert len(doc["scenes"]) == 2 and doc["voice"] == {"provider": "system", "voice_id": "", "rate_pct": 0}
    assert doc["audience"]["country"] == "CA" and doc["captions"]["enabled"] is True
    assert client.get(f"/api/projects/{doc['id']}").status_code == 200

    r = client.post("/api/projects/script", json={
        "kind": "reddit", "text": "I told u/someone_else to stop. They did not.", "country": "US",
        "reddit": {"community": "r/test", "title": "My story", "source_url": "https://www.reddit.com/r/test/"}})
    assert r.status_code == 200, r.text
    body = r.json()
    doc = body["project"]
    assert body["usernames_replaced"] == 1 and doc["voice"]["provider"] == "edge"
    assert doc["scenes"][0]["overlays"]["reddit_card"]["author"]["mode"] == "hidden"
    assert "u/someone_else" not in str(doc["scenes"])

    r = client.post("/api/projects/script", json={"kind": "ranking_list", "text": "Alpha\nBeta\nGamma"})
    assert r.status_code == 200 and r.json()["project"]["ranking"]["enabled"] is True
    assert client.post("/api/projects/script", json={"kind": "blank"}).status_code == 200


def test_create_from_script_rejects_bad_input(client):
    assert client.post("/api/projects/script", json={"kind": "script", "text": "x", "voice_provider": "robot"}).status_code == 400
    assert client.post("/api/projects/script", json={"kind": "poem", "text": "x"}).status_code == 400
    assert client.post("/api/projects/script", json={"kind": "script", "text": "   "}).status_code == 422


def test_rasters_are_served_after_resolve(client):
    doc = client.post("/api/projects/script", json={"kind": "ranking_list", "text": "One entry\nTwo entry"}).json()["project"]
    tl = client.post("/api/resolve", json={"project": doc}).json()
    assert "rasters" not in tl
    rid = next(o["raster"] for o in tl["scenes"][0]["overlays"] if o["kind"] == "badge")
    r = client.get(f"/api/raster/{rid}.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    assert client.get("/api/raster/r" + "0" * 31 + ".png").status_code == 404
    assert client.get("/api/raster/../secrets").status_code == 404


@needs_ffmpeg
def test_sound_effects(client):
    r = client.get("/api/sfx/whoosh")
    assert r.status_code == 200 and r.content[:4] == b"RIFF"
    assert client.get("/api/sfx/explosion").status_code == 404


@needs_ffmpeg
@windows_only
def test_take_generate_play_and_upload(client, tmp_path):
    doc = client.post("/api/projects/script", json={"kind": "script", "text": "A short line for the test voice.",
                                                    "voice_provider": "system"}).json()["project"]
    pid, sid = doc["id"], doc["scenes"][0]["id"]
    voices = client.get("/api/voices?provider=system").json()
    assert voices["online"] is True and voices["voices"]
    r = client.post(f"/api/projects/{pid}/takes", json={"scene_id": sid, "text": doc["scenes"][0]["narration"]["text"],
                                                       "provider": "system", "voice_id": "", "rate_pct": 0})
    j = job(client, r.json()["job_id"])
    assert j["status"] == "done", j
    take = j["result"]["take"]
    assert j["result"]["scene_id"] == sid and take["method"] == "tts" and take["voice_id"] == ""
    name = take["audio_path"].rsplit("/", 1)[-1]
    wav = client.get(f"/api/takes/{name}")
    assert wav.status_code == 200 and wav.content[:4] == b"RIFF"
    assert client.get("/api/takes/..%2F..%2Fdb.sqlite").status_code == 404
    # Attach it: the scene's voice is ready, so the timeline has no voice warning.
    doc["scenes"][0]["narration"]["take"] = take
    tl = client.post("/api/resolve", json={"project": doc}).json()
    assert not [i for i in tl["issues"] if i["code"] in ("voice_missing", "voice_stale")]
    assert tl["scenes"][0]["narration"]["state"] == "ready"

    # A recording (here: the generated WAV, uploaded as a file) becomes a take with estimated word timing.
    up = client.post(f"/api/projects/{pid}/takes/upload", files={"file": ("rec.wav", wav.content, "audio/wav")},
                     data={"scene_id": sid, "text": "A short line for the test voice.", "method": "recorded"})
    assert up.status_code == 200, up.text
    rec = up.json()["take"]
    assert rec["method"] == "recorded" and rec["timing"] == "estimated" and len(rec["words"]) == 7
    bad = client.post(f"/api/projects/{pid}/takes/upload", files={"file": ("notes.txt", b"hi", "text/plain")},
                      data={"scene_id": sid, "text": "x"})
    assert bad.status_code == 400


@needs_ffmpeg
def test_gameplay_library_pick_and_preview_join(client, tmp_path):
    clip_file = bands_video(tmp_path / "gp-4s.mp4", seconds=4)
    r = client.post("/api/gameplay", json={"paths": [str(clip_file), str(tmp_path / "missing.mp4")], "tags": ["Test", " "]})
    body = r.json()
    assert len(body["clips"]) == 1 and len(body["errors"]) == 1
    clip = body["clips"][0]
    assert clip["tags"] == ["test"] and clip["uses"] == 0
    assert client.patch(f"/api/gameplay/{clip['id']}", json={"tags": ["Runs", "speed"]}).json()["tags"] == ["runs", "speed"]

    # Clips over gameplay: one 10 s clip on top, the 4 s gameplay loops under it.
    top = bands_video(tmp_path / "top-10s.mp4", seconds=10)
    r = client.post("/api/projects/gameplay", json={"paths": [str(top)], "gameplay_clip_id": clip["id"], "layout": "split"})
    assert r.status_code == 200, r.text
    doc = r.json()["project"]
    tl = client.post("/api/resolve", json={"project": doc}).json()
    loop = tl["scenes"][0]["layers"][1]["loop"]
    assert loop["joins"] == [3.75, 7.5]
    clip_mp4 = client.post(f"/api/projects/{doc['id']}/preview-clip",
                           json={"project": doc, "scene_id": doc["scenes"][0]["id"], "t0": 2.75, "t1": 4.75})
    assert clip_mp4.status_code == 200 and clip_mp4.headers["content-type"] == "video/mp4" and len(clip_mp4.content) > 1000

    # A further pick for an existing project avoids the stretch used before when there is room; here there isn't,
    # so it reports the overlap and that the clip will loop.
    pick = client.post(f"/api/gameplay/{clip['id']}/pick", json={"seconds": 6, "project_id": doc["id"]}).json()
    assert pick["loop_needed"] is True and pick["segment"]["created_by"] == "gameplay_pick"
    assert client.get(f"/api/media/{pick['source_id']}/info").status_code == 200
    assert next(c for c in client.get("/api/gameplay").json()["clips"] if c["id"] == clip["id"])["uses"] == 2
    assert client.delete(f"/api/gameplay/{clip['id']}").json()["ok"] is True
    assert client.post(f"/api/gameplay/{clip['id']}/pick", json={"seconds": 3}).status_code == 404


@needs_ffmpeg
def test_sample_music_and_sample_gameplay(client):
    doc = client.post("/api/projects/script", json={"kind": "blank"}).json()["project"]
    r = client.post(f"/api/projects/{doc['id']}/music/sample")
    assert r.status_code == 200
    (sid, src), = r.json()["sources"].items()
    assert src["kind"] == "audio" and src["origin"] == "generated" and src["fingerprint"]["duration_s"] > 10
    j = job(client, client.post("/api/gameplay/sample").json()["job_id"])
    assert j["status"] == "done", j
    assert j["result"]["clip"]["sample"] is True and j["result"]["clip"]["fingerprint"]["duration_s"] >= 59

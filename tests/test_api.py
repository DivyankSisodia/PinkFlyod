"""The HTTP API, including a full import -> edit -> save -> export -> reopen round trip."""
from __future__ import annotations

import pytest
from conftest import needs_ffmpeg, wait_for_job
from fastapi.testclient import TestClient

from shorts_studio.app import create_app

TOKEN = "test-token"


@pytest.fixture
def client(settings):
    app = create_app(settings, extra_hosts={"testserver"}, token=TOKEN)
    with TestClient(app) as c:
        c.headers["X-Studio-Token"] = TOKEN
        yield c


def test_health_and_session(client):
    h = client.get("/api/health").json()
    assert h["ok"] is True and h["version"]
    assert client.get("/api/session").json()["token"] == TOKEN


def test_writes_need_the_token(settings):
    app = create_app(settings, extra_hosts={"testserver"}, token=TOKEN)
    with TestClient(app) as c:
        r = c.post("/api/projects", json={"preset": "quick_short", "paths": ["x.mp4"]})
        assert r.status_code == 403
        assert c.get("/api/projects").status_code == 200


def test_unknown_host_is_refused(settings):
    app = create_app(settings, token=TOKEN)
    with TestClient(app, base_url="http://evil.example") as c:
        assert c.get("/api/health").status_code == 421


def test_bad_import_reports_errors(client, tmp_path):
    bogus = tmp_path / "notes.txt"
    bogus.write_text("hi")
    r = client.post("/api/projects", json={"preset": "quick_short", "paths": [str(bogus)]})
    assert r.status_code == 422 and "isn't supported" in r.json()["detail"]


@needs_ffmpeg
def test_import_edit_save_export_reopen(client, landscape):
    r = client.post("/api/projects", json={"preset": "quick_short", "paths": [str(landscape)]})
    assert r.status_code == 200, r.text
    doc = r.json()["project"]
    pid = doc["id"]

    # The editor's resolve call (preview data).
    tl = client.post("/api/resolve", json={"project": doc}).json()
    assert tl["frames"] == 390 and tl["audible"] is True

    # Edit: crop focus to the left quarter, then save.
    doc["scenes"][0]["layers"]["primary"]["reframe"]["focus"]["x"] = 0.25
    saved = client.put(f"/api/projects/{pid}", json={"base_revision": doc["revision"], "project": doc})
    assert saved.status_code == 200, saved.text
    doc["revision"] = saved.json()["revision"]

    # A second save from a stale copy is refused.
    stale = client.put(f"/api/projects/{pid}", json={"base_revision": 1, "project": doc})
    assert stale.status_code == 409 and stale.json()["current_revision"] == doc["revision"]

    # Exporting needs the saved revision.
    assert client.post(f"/api/projects/{pid}/render", json={"revision": 1}).status_code == 409
    job_id = client.post(f"/api/projects/{pid}/render", json={"revision": doc["revision"]}).json()["job_id"]
    job = wait_for_job(lambda j: client.get(f"/api/jobs/{j}").json(), job_id)
    assert job["status"] == "done", job
    render_id = job["result"]["render_id"]
    render = client.get(f"/api/renders/{render_id}").json()
    assert render["verify"]["ok"] is True and render["revision"] == doc["revision"]
    assert render["verify"]["summary"]["width"] == 1080 and render["verify"]["summary"]["frames"] == 390

    # The file is served with range support (the browser player needs it).
    part = client.get(f"/api/renders/{render_id}/file", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100

    # Reopen: the saved edit is there, along with the render.
    reopened = client.get(f"/api/projects/{pid}").json()
    assert reopened["project"]["scenes"][0]["layers"]["primary"]["reframe"]["focus"]["x"] == 0.25
    assert reopened["statuses"] == {sid: "ok" for sid in doc["sources"]}
    assert reopened["renders"][0]["id"] == render_id
    assert client.get("/api/projects").json()["projects"][0]["id"] == pid


@needs_ffmpeg
def test_exact_frame_and_media_endpoints(client, landscape):
    doc = client.post("/api/projects", json={"preset": "quick_short", "paths": [str(landscape)]}).json()["project"]
    r = client.post(f"/api/projects/{doc['id']}/frame", json={"project": doc, "t": 2.0})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    sid = next(iter(doc["sources"]))
    info = client.get(f"/api/media/{sid}/info").json()
    assert info["exists"] is True and info["proxy_state"] == "none"
    part = client.get(f"/api/media/{sid}/file", headers={"Range": "bytes=0-1023"})
    assert part.status_code == 206


@needs_ffmpeg
def test_add_sources_and_relink_check(client, landscape, landscape_silent):
    doc = client.post("/api/projects", json={"preset": "quick_short", "paths": [str(landscape)]}).json()["project"]
    added = client.post(f"/api/projects/{doc['id']}/sources", json={"paths": [str(landscape_silent)]}).json()
    assert len(added["sources"]) == 1 and added["errors"] == []
    record = next(iter(doc["sources"].values()))
    check = client.post("/api/relink/check", json={"path": str(landscape_silent), "source": record}).json()
    assert check["ok"] is True and check["compatible"] is False


@needs_ffmpeg
def test_render_blocked_by_missing_media(client, landscape, tmp_path):
    import shutil
    own = tmp_path / "mine.mp4"
    shutil.copy2(landscape, own)
    doc = client.post("/api/projects", json={"preset": "quick_short", "paths": [str(own)]}).json()["project"]
    own.unlink()
    job_id = client.post(f"/api/projects/{doc['id']}/render", json={"revision": doc["revision"]}).json()["job_id"]
    job = wait_for_job(lambda j: client.get(f"/api/jobs/{j}").json(), job_id)
    assert job["status"] == "failed" and "missing" in job["error"]
    assert client.get(f"/api/projects/{doc['id']}").json()["statuses"] == {next(iter(doc["sources"])): "missing"}

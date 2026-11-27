"""Deleting old exports and whole projects frees space without touching anything another project still uses."""
from __future__ import annotations

import shutil

import pytest
from conftest import needs_ffmpeg, wait_for_job
from fastapi.testclient import TestClient

from shorts_studio import trash
from shorts_studio.app import create_app

TOKEN = "test-cleanup"


@pytest.fixture
def client(settings, monkeypatch):
    # Tests delete outright; the Recycle Bin path is covered by test_trash_on_windows.
    monkeypatch.setattr(trash, "_windows_recycle", lambda paths: False)
    app = create_app(settings, extra_hosts={"testserver"}, token=TOKEN)
    with TestClient(app, headers={"X-Studio-Token": TOKEN}) as c:
        yield c


def export(client, pid, revision):
    job = wait_for_job(lambda j: client.get(f"/api/jobs/{j}").json(),
                       client.post(f"/api/projects/{pid}/render", json={"revision": revision}).json()["job_id"])
    assert job["status"] == "done", job
    return client.get(f"/api/renders/{job['result']['render_id']}").json()


def copy_in(client, path):
    with open(path, "rb") as f:
        r = client.post("/api/uploads", files={"file": (path.name, f, "video/mp4")})
    assert r.status_code == 200, r.text
    return r.json()["path"]


@needs_ffmpeg
def test_delete_old_exports_and_a_project(client, settings, landscape_silent, tmp_path):
    linked = tmp_path / "mine" / "my-own-clip.mp4"            # a file of yours, linked in place
    linked.parent.mkdir()
    shutil.copy2(landscape_silent, linked)
    copied = copy_in(client, landscape_silent)                # a file copied into data/media/imports

    a = client.post("/api/projects", json={"paths": [copied], "preset": "quick_short"}).json()["project"]
    b = client.post("/api/projects", json={"paths": [str(linked)], "preset": "quick_short"}).json()["project"]
    r1, r2, r3 = (export(client, a["id"], a["revision"]) for _ in range(3))
    assert all(r["exists"] for r in (r1, r2, r3))

    # One export.
    assert client.delete(f"/api/renders/{r1['id']}").json()["ok"]
    assert client.get(f"/api/renders/{r1['id']}").status_code == 404
    assert not (settings.projects_dir / a["id"] / "renders").joinpath(r1["path"].split("\\")[-1].split("/")[-1]).exists()

    # Keep only the newest.
    out = client.post(f"/api/projects/{a['id']}/renders/prune", json={"keep": 1}).json()
    assert out["deleted"] == 1 and out["freed_bytes"] > 0
    left = client.get(f"/api/projects/{a['id']}/renders").json()["renders"]
    assert [r["id"] for r in left] == [r3["id"]] and left[0]["exists"]

    # The whole project: its folder, exports, records and the copied-in file go; project B and your file stay.
    preview = client.get(f"/api/projects/{a['id']}/delete-preview").json()
    assert preview["exports"] == 1 and len(preview["media_files"]) == 1 and preview["total_bytes"] > 0
    copied_path = settings.resolve_media_path(next(iter(a["sources"].values()))["path"])
    assert copied_path.is_file()
    assert client.delete(f"/api/projects/{a['id']}").json()["ok"]
    assert not (settings.projects_dir / a["id"]).exists()
    assert not copied_path.exists() and not copied_path.parent.exists()
    assert client.get(f"/api/projects/{a['id']}").status_code == 404
    assert client.get(f"/api/renders/{r3['id']}").status_code == 404
    assert [p["id"] for p in client.get("/api/projects").json()["projects"]] == [b["id"]]
    assert linked.is_file()                                   # never touches your own files

    preview_b = client.get(f"/api/projects/{b['id']}/delete-preview").json()
    assert preview_b["media_files"] == []                     # linked from outside the data folder: kept
    assert client.delete(f"/api/projects/{b['id']}").json()["ok"] and linked.is_file()


@needs_ffmpeg
def test_media_shared_by_two_projects_is_kept(client, settings, landscape_silent):
    copied = copy_in(client, landscape_silent)
    a = client.post("/api/projects", json={"paths": [copied], "preset": "quick_short"}).json()["project"]
    b = client.post("/api/projects", json={"paths": [copied], "preset": "quick_short"}).json()["project"]
    assert client.get(f"/api/projects/{a['id']}/delete-preview").json()["media_files"] == []
    assert client.delete(f"/api/projects/{a['id']}").json()["ok"]
    path = settings.resolve_media_path(next(iter(b["sources"].values()))["path"])
    assert path.is_file() and client.get(f"/api/projects/{b['id']}").status_code == 200


def test_unknown_items_and_paths_outside_projects(client, settings, tmp_path):
    assert client.delete("/api/projects/prj_01ABCDEFGHJKMNPQRSTVWXYZ0").status_code == 404
    assert client.delete("/api/projects/..%2F..%2Fdata").status_code in (404, 405)
    assert client.delete("/api/renders/ren_doesnotexist").status_code == 404
    from shorts_studio.db import Database
    outside = tmp_path / "elsewhere.mp4"
    outside.write_bytes(b"x")
    Database(settings.db_path).insert_render("ren_outside", "prj_01ABCDEFGHJKMNPQRSTVWXYZ0", 1, outside, {}, [])
    assert client.delete("/api/renders/ren_outside").status_code == 400 and outside.is_file()


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows Recycle Bin")
def test_trash_on_windows(tmp_path):
    f = tmp_path / "old-export.mp4"
    f.write_bytes(b"0" * 100)
    folder = tmp_path / "old-project"
    (folder / "renders").mkdir(parents=True)
    (folder / "renders" / "a.mp4").write_bytes(b"1")
    assert trash.to_trash([f, folder]) is True
    assert not f.exists() and not folder.exists()

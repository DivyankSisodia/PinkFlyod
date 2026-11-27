from __future__ import annotations

import base64
import io
import json
import shutil
from pathlib import Path
from urllib.error import HTTPError

import pytest
from conftest import needs_ffmpeg, wait_for_job
from fastapi.testclient import TestClient

from shorts_studio import providers
from shorts_studio.app import create_app
from shorts_studio.media import download
from shorts_studio.render.ffmpeg import run


@pytest.fixture
def client(settings):
    app = create_app(settings, extra_hosts={"testserver"}, token="test-workflows")
    with TestClient(app, headers={"X-Studio-Token": "test-workflows"}) as conn:
        yield conn


def wait(client, response):
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    job = wait_for_job(lambda jid: client.get(f"/api/jobs/{jid}").json(), job_id)
    stages = [row["stage"] for row in client.get(f"/api/jobs/{job_id}/checkpoints").json()["checkpoints"]]
    return job, stages


@needs_ffmpeg
def test_import_three_links_and_export(client, settings, monkeypatch, landscape_silent):
    def fetch(url, folder, cancel, progress):
        folder.mkdir()
        path = folder / "video.mp4"
        shutil.copyfile(landscape_silent, path)
        progress(1)
        return path, {"youtube": "Example clip", "instagram": "Example Reel", "direct": "Gameplay clip"}[download.checked_url(url)]

    monkeypatch.setattr(download, "fetch", fetch)
    assert client.post("/api/urls/import", json={"youtube": "https://example.com/gameplay.mp4"}).status_code == 422
    job, stages = wait(client, client.post("/api/urls/import", json={
        "youtube": "https://www.youtube.com/watch?v=abc", "instagram": "https://www.instagram.com/reel/abc/",
        "gameplay": "https://example.com/gameplay.mp4", "layout": "pip", "tags": ["Driving"],
    }))
    assert job["status"] == "done", job
    assert stages == ["Queued", "Starting", "Downloading YouTube video", "Checking YouTube video",
                      "Downloading Instagram Reel", "Checking Instagram Reel", "Downloading gameplay video",
                      "Checking gameplay video", "Saving gameplay to the library", "Creating the editable short", "Done"]
    clip, = client.get("/api/gameplay").json()["clips"]
    assert clip["downloaded"] and clip["tags"] == ["driving"] and clip["id"] == job["result"]["clip_id"]
    assert Path(clip["path"]).is_relative_to(settings.gameplay_dir) and Path(clip["path"]).is_file()
    project_url = f"/api/projects/{job['result']['project_id']}"
    doc = client.get(project_url).json()["project"]
    assert doc["origin"]["input"] == "url"
    assert [scene["layout"]["type"] for scene in doc["scenes"]] == ["pip", "pip"]
    assert [source["origin"] for source in doc["sources"].values()].count("url_download") == 2
    assert client.post("/api/resolve", json={"project": doc}).json()["needs_rights"] is True
    doc["compliance"]["rights"].update(confirmed=True, confirmed_at="2026-11-26T00:00:00Z")
    saved = client.put(project_url, json={"base_revision": doc["revision"], "project": doc})
    assert saved.status_code == 200, saved.text
    rendered, _ = wait(client, client.post(project_url + "/render", json={"revision": saved.json()["revision"]}))
    assert rendered["status"] == "done", rendered
    report = client.get(f"/api/renders/{rendered['result']['render_id']}").json()
    assert report["verify"]["ok"] and Path(report["path"]).is_file()


def test_direct_url_cannot_target_loopback(client):
    job, stages = wait(client, client.post("/api/urls/import", json={"gameplay": "http://127.0.0.1/video.mp4"}))
    assert job["status"] == "failed" and "public video URL" in job["error"]
    assert stages[-1] == "Failed"
    assert client.get("/api/gameplay").json() == {"clips": []}


def test_save_opencode_model_preserves_key_and_accepts_config_id(client):
    config = {"opencode_key": "fixture-console-key", "opencode_model": "glm-5.3-flash"}
    assert client.put("/api/providers", json=config).json()["opencode_model"] == "glm-5.3-flash"
    response = client.put("/api/providers", json={"opencode_model": "opencode-go/kimi-k3"})
    assert response.status_code == 200
    assert response.json()["opencode_model"] == "kimi-k3"
    assert response.json()["opencode_configured"] is True

    for value, expected in (({"opencode_model": "Kimi K3"}, "writing model"),
                            ({"opencode_key": "label fixture-console-key"}, "API key"),
                            ({"opencode_model": "z" * 200}, "writing model"),
                            ({"opencode_model": "opencode-go/"}, "writing model")):
        response = client.put("/api/providers", json=value)
        assert response.status_code == 422
        assert expected in response.json()["detail"] and "fixture-console-key" not in response.text
    assert client.get("/api/providers").json()["opencode_model"] == "kimi-k3"


@needs_ffmpeg
def test_timeline_intro_uses_video_frames_and_title_without_generating_audio(client, monkeypatch, landscape_silent):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-go-key")
    monkeypatch.setenv("OPENCODE_GO_MODEL", "test-vision-model")
    requests = []

    def fake_json(provider, url, headers, payload=None):
        assert provider == "OpenCode Go"
        if url.endswith("/v1/models"):
            return {"data": [{"id": "test-vision-model", "modalities": {"input": ["text", "image/jpeg"]}}]}
        requests.append(payload)
        return {"choices": [{"message": {"content": "Wait until the colors change."}}]}

    monkeypatch.setattr(providers, "_json", fake_json)
    project = client.post("/api/projects", json={"paths": [str(landscape_silent)], "title": "Changing colors"}).json()["project"]
    project["scenes"][0]["duration"] = {"driver": "fixed", "fixed_s": 3, "tail_pad_s": 0}
    url = f"/api/projects/{project['id']}"
    saved = client.put(url, json={"project": project, "base_revision": project["revision"]})
    assert saved.status_code == 200
    revision = saved.json()["revision"]
    assert client.post(url + "/intro-draft", json={"revision": 1}).status_code == 409
    job, stages = wait(client, client.post(url + "/intro-draft", json={"revision": revision, "notes": "A quick reveal"}))
    assert job["status"] == "done", job
    assert job["result"]["script"] == "Wait until the colors change."
    assert job["result"]["opening_seconds"] == 3
    assert "Sampling the opening clip" in stages and "Intro ready for your review" in stages
    payload, = requests
    assert payload["model"] == "test-vision-model"
    prompt = payload["messages"][1]["content"]
    assert "Project title: Changing colors" in prompt[0]["text"]
    assert "Source title: " in prompt[0]["text"] and "A quick reveal" in prompt[0]["text"]
    # No word budget from the 3 s opening scene: the model decides; only the whole clip bounds the length.
    assert "spoken words" not in prompt[0]["text"] and "at most" not in prompt[0]["text"]
    clip = project["segments"][project["scenes"][0]["layers"]["primary"]["segment_id"]]
    assert job["result"]["max_seconds"] == round(clip["out_s"] - clip["in_s"], 2)
    assert f"{job['result']['max_seconds']:.1f} seconds long" in prompt[0]["text"]
    system = payload["messages"][0]["content"]
    assert system.startswith(providers.SHORTS_STYLE) and "Watch what happens" in system
    images = [part["image_url"]["url"] for part in prompt if part["type"] == "image_url"]
    assert len(images) == 6 and all(base64.b64decode(image.split(",", 1)[1]).startswith(b"\xff\xd8") for image in images)
    latest = client.get(url).json()["project"]
    assert latest["scenes"][0]["narration"] is None and latest["revision"] == revision


@pytest.mark.parametrize(("route", "credential", "status", "body", "message"), [
    ("elevenlabs/options", "elevenlabs_key", 401,
     {"detail": {"status": "missing_permissions", "message": "models_read private-response"}}, "Models → Read"),
    ("elevenlabs/options?kind=voices", "elevenlabs_key", 401,
     {"detail": {"status": "missing_permissions", "message": "voices_read private-response"}}, "Voices → Read"),
    ("opencode/access", "opencode_key", 403,
     {"error": {"type": "EntitlementError", "message": "OpenCode Go subscription required. private-response"}},
     "requires an active Go subscription"),
    ("opencode/options", "opencode_key", 403,
     {"detail": "Request blocked private-response"}, "The network blocked"),
])
def test_provider_denials_explain_the_cause_without_echoing_upstream(client, monkeypatch, route, credential, status,
                                                                   body, message):
    class FailedConnection:
        def open(self, request, timeout):
            assert request.get_header("User-agent").startswith("ShortsStudio/")
            raise HTTPError(request.full_url, status, "test", {}, io.BytesIO(json.dumps(body).encode()))

    client.put("/api/providers", json={credential: "fake-provider-key"})
    monkeypatch.setattr(providers, "build_opener", lambda *_: FailedConnection())
    response = client.get(f"/api/providers/{route}")
    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert "private-response" not in response.text and "fake-provider-key" not in response.text


@needs_ffmpeg
def test_provider_secrets_drafts_and_timed_voice(client, settings, monkeypatch, tmp_path):
    eleven = "fake-elevenlabs-secret"
    opencode = "fake-opencode-secret"
    wav = tmp_path / "voice.mp3"
    run(["-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(wav)], label="test voice")
    characters = list("Hi there.")
    starts = [i * 0.08 for i in range(len(characters))]

    def fake_json(provider, url, headers, payload=None):
        if provider == "OpenCode Go":
            assert headers["Authorization"] == "Bearer " + opencode
            if payload is None:
                return {"data": [{"id": "writer", "type": "chat"}, {"id": "image", "type": "image"}]}
            assert "x-opencode-session" in headers and payload["model"] == "writer"
            return {"choices": [{"message": {"content": "Hi there."}}]}
        assert headers["xi-api-key"] == eleven
        if url.endswith("/v1/models"):
            return [{"model_id": "speaker-model", "can_do_text_to_speech": True}]
        if "/v2/voices?" in url:
            return {"voices": [{"voice_id": "voice-id", "name": "Testing voice"}]}
        if url.endswith("/v1/user/subscription"):
            return {"tier": "free"}
        assert payload == {"text": "Hi there.", "model_id": "speaker-model"}
        return {"audio_base64": base64.b64encode(wav.read_bytes()).decode(), "alignment": {
            "characters": characters, "character_start_times_seconds": starts,
            "character_end_times_seconds": [value + 0.06 for value in starts],
        }}

    monkeypatch.setattr(providers, "_json", fake_json)
    assert client.put("/api/providers", json={"elevenlabs_key": {"key": eleven}}).status_code == 422
    saved = client.put("/api/providers", json={"opencode_key": opencode, "elevenlabs_key": eleven,
                       "opencode_model": "writer", "elevenlabs_model": "speaker-model", "elevenlabs_voice": "voice-id"})
    assert saved.status_code == 200, saved.text
    for response in (saved, client.get("/api/providers")):
        assert opencode not in response.text and eleven not in response.text
        assert response.json()["opencode_configured"] and response.json()["elevenlabs_configured"]
    assert eleven.encode() not in (settings.data_dir / "studio.db").read_bytes()
    assert client.get("/api/providers/opencode/options").json()["options"] == [{"id": "writer", "name": "writer"}]
    assert client.get("/api/providers/elevenlabs/options?kind=voices").json()["options"][0]["id"] == "voice-id"
    assert client.get("/api/providers/elevenlabs/options").json()["options"][0]["id"] == "speaker-model"

    draft, stages = wait(client, client.post("/api/drafts/topic", json={"topic": "Welcome", "country": "CA"}))
    assert draft["result"] == {"script": "Hi there.", "country": "CA"} and "Draft ready for review" in stages
    doc = client.post("/api/projects/script", json={"kind": "script", "text": draft["result"]["script"],
                      "voice_provider": "elevenlabs", "from_topic": True}).json()["project"]
    assert doc["origin"]["input"] == "topic" and doc["voice"]["model_id"] == "speaker-model"
    scene = doc["scenes"][0]
    job, stages = wait(client, client.post(f"/api/projects/{doc['id']}/takes", json={
        **doc["voice"], "text": scene["narration"]["text"], "scene_id": scene["id"],
    }))
    assert job["status"] == "done" and "Preparing audio and caption timings" in stages
    take = scene["narration"]["take"] = job["result"]["take"]
    assert take["timing"] == "native" and len(take["words"]) == 2
    assert client.post("/api/resolve", json={"project": doc}).json()["scenes"][0]["narration"]["state"] == "ready"
    doc["voice"]["model_id"] = "new-model"
    assert client.post("/api/resolve", json={"project": doc}).json()["scenes"][0]["narration"]["state"] == "stale"


def test_free_plan_library_voice_is_explained_not_called_a_credit_problem(client, monkeypatch):
    """ElevenLabs answers 402 paid_plan_required for Voice Library speakers on free plans, with credits left."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-eleven-key")
    library = {"voice_id": "lib-voice", "name": "Titan", "category": "professional", "sharing": {"status": "copied"}}
    default = {"voice_id": "default-voice", "name": "Liam", "category": "premade", "sharing": None}

    def fake_json(provider, url, headers, payload=None):
        if "/v2/voices?" in url:
            return {"voices": [library, default]}
        if url.endswith("/v1/user/subscription"):
            return {"tier": "free", "character_count": 0, "character_limit": 10000}
        raise AssertionError(url)

    monkeypatch.setattr(providers, "_json", fake_json)
    names = {o["id"]: o["name"] for o in client.get("/api/providers/elevenlabs/options?kind=voices").json()["options"]}
    assert names == {"lib-voice": "Titan (needs a paid ElevenLabs plan)", "default-voice": "Liam"}

    body = json.dumps({"detail": {"type": "payment_required", "code": "paid_plan_required", "status": "payment_required",
                                  "message": "Free users cannot use library voices via the API."}}).encode()
    error = HTTPError("https://api.elevenlabs.io/v1/text-to-speech/lib-voice/with-timestamps", 402, "Payment Required",
                      {}, io.BytesIO(body))
    message = providers._http_error("ElevenLabs", error.url, error)
    assert "free plans can’t use library voices" in message and "credits are fine" in message
    quota = HTTPError(error.url, 402, "Payment Required", {}, io.BytesIO(json.dumps(
        {"detail": {"status": "quota_exceeded", "message": "No credits."}}).encode()))
    assert "insufficient credits" in providers._http_error("ElevenLabs", error.url, quota)

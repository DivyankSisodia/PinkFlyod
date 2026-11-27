"""Every OpenCode Go request and response is written to data/logs/opencode-api.jsonl, without the API key."""
from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest

from shorts_studio import ai_log, providers

KEY = "sk-test-SECRET-key-1234567890"


class FakeResponse:
    def __init__(self, status: int, body: bytes):
        self.status, self._body = status, body

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, reply):
        self.reply, self.requests = reply, []

    def open(self, request, timeout=None):
        self.requests.append(request)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def log_file(settings):
    providers.ProviderSettings(settings)                 # the app configures the log this way at start-up
    return settings.logs_dir / ai_log.FILE_NAME


def entries(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def config():
    return {"OPENCODE_GO_API_KEY": KEY, "OPENCODE_GO_MODEL": "kimi-k3"}


def test_chat_request_and_response_are_logged_without_the_key(monkeypatch, log_file):
    reply = {"id": "chatcmpl-1", "choices": [{"message": {"role": "assistant", "content": "A hook line."}}],
             "usage": {"prompt_tokens": 120, "completion_tokens": 6}}
    opener = FakeOpener(FakeResponse(200, json.dumps(reply).encode()))
    monkeypatch.setattr(providers, "build_opener", lambda *_: opener)
    frame = "data:image/jpeg;base64," + "A" * 4000
    content = [{"type": "text", "text": f"Key in the text by mistake: {KEY}"},
               {"type": "image_url", "image_url": {"url": frame}}]
    assert providers.go_chat(config(), "Write a hook.", content, "job_01ABCDEFGHJKMNPQRSTVWXYZ00") == "A hook line."
    # The real request still carried the real key.
    assert opener.requests[0].get_header("Authorization") == f"Bearer {KEY}"

    text = log_file.read_text(encoding="utf-8")
    assert KEY not in text
    (e,) = entries(log_file)
    assert e["provider"] == "OpenCode Go" and e["method"] == "POST" and e["status"] == 200
    assert e["url"].endswith("/openai/v1/chat/completions")
    assert e["request"]["headers"]["Authorization"] == "Bearer ***"
    body = e["request"]["body"]
    assert body["model"] == "kimi-k3" and body["messages"][0] == {"role": "system", "content": "Write a hook."}
    user = body["messages"][1]["content"]
    assert user[0]["text"] == "Key in the text by mistake: ***"
    assert user[1]["image_url"]["url"] == "<image/jpeg base64, 3000 bytes, omitted>"
    assert e["response"]["body"] == reply
    assert isinstance(e["duration_ms"], int) and e["id"].startswith("call_") and e["ts"].endswith("Z")


def test_http_errors_are_logged_with_their_body_and_message(monkeypatch, log_file):
    err_body = json.dumps({"error": {"type": "EntitlementError", "message": "no access"}}).encode()
    error = HTTPError("https://opencode.ai/inference/go/openai/v1/chat/completions", 403, "Forbidden", {},
                      io.BytesIO(err_body))
    monkeypatch.setattr(providers, "build_opener", lambda *_: FakeOpener(error))
    with pytest.raises(providers.ProviderError, match="does not cover this request"):
        providers.go_chat(config(), "Write.", "topic", "job_01ABCDEFGHJKMNPQRSTVWXYZ00")
    (e,) = entries(log_file)
    assert e["status"] == 403 and e["response"]["body"]["error"]["type"] == "EntitlementError"
    assert "does not cover this request" in e["error"]


def test_connection_failures_are_logged(monkeypatch, log_file):
    monkeypatch.setattr(providers, "build_opener", lambda *_: FakeOpener(OSError("network down")))
    with pytest.raises(providers.ProviderError):
        providers.go_chat(config(), "Write.", "topic", "job_01ABCDEFGHJKMNPQRSTVWXYZ00")
    (e,) = entries(log_file)
    assert e["status"] is None and e["response"] is None and "network down" in e["error"]


def test_elevenlabs_calls_are_not_logged(monkeypatch, log_file):
    monkeypatch.setattr(providers, "build_opener", lambda *_: FakeOpener(FakeResponse(200, b"[]")))
    providers._json("ElevenLabs", "https://api.elevenlabs.io/v1/models", {"xi-api-key": KEY})
    assert not log_file.exists()


def test_log_rotates(monkeypatch, log_file):
    monkeypatch.setattr(ai_log, "MAX_BYTES", 600)
    monkeypatch.setattr(providers, "build_opener",
                        lambda *_: FakeOpener(FakeResponse(200, json.dumps({"data": [], "pad": "x" * 300}).encode())))
    for _ in range(5):
        providers._json("OpenCode Go", "https://opencode.ai/inference/go/v1/models", {"Authorization": f"Bearer {KEY}"})
    names = sorted(p.name for p in log_file.parent.glob(ai_log.FILE_NAME + "*"))
    assert names == [ai_log.FILE_NAME, *(f"{ai_log.FILE_NAME}.{i}" for i in range(1, 4))]
    assert all(KEY not in p.read_text(encoding="utf-8") for p in log_file.parent.glob(ai_log.FILE_NAME + "*"))


def test_reasoning_model_that_runs_out_of_tokens_gets_a_clear_error(monkeypatch, log_file):
    reply = {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": ""}}],
             "usage": {"completion_tokens": 16000, "completion_tokens_details": {"reasoning_tokens": 15998}}}
    opener = FakeOpener(FakeResponse(200, json.dumps(reply).encode()))
    monkeypatch.setattr(providers, "build_opener", lambda *_: opener)
    with pytest.raises(providers.ProviderError, match="used its whole answer budget thinking"):
        providers.go_chat(config(), "Write.", "topic", "job_01ABCDEFGHJKMNPQRSTVWXYZ00")
    sent = json.loads(opener.requests[0].data)
    assert sent["max_completion_tokens"] == 16000

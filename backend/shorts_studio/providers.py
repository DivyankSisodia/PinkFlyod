"""Optional AI integrations. Credentials stay server-side in the workspace's .env file."""
from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import BaseModel, Field, SecretStr

from . import __version__, ai_log
from .config import Settings
from .timeline.words import Word

GO = "https://opencode.ai/inference/go"
ELEVEN = "https://api.elevenlabs.io"
DEFAULT_ELEVEN_MODEL = "eleven_multilingual_v2"
MODEL_ID = re.compile(r"[\w.:-]{1,100}", re.ASCII)
KEYS = {"OPENCODE_GO_API_KEY", "ELEVENLABS_API_KEY", "OPENCODE_GO_MODEL", "ELEVENLABS_MODEL", "ELEVENLABS_VOICE"}
SETTING_ERRORS = {
    "opencode_key": "Enter only the OpenCode Go API key, without its label or any extra characters.",
    "elevenlabs_key": "Enter only the ElevenLabs API key, without its label or any extra characters.",
    "opencode_model": "Choose a writing model from Load models or enter its model ID, for example kimi-k3.",
    "elevenlabs_model": "Choose an ElevenLabs voice model from Load models or enter its model ID.",
    "elevenlabs_voice": "Choose an ElevenLabs speaker from Load speakers or enter its voice ID.",
}


class ProviderError(Exception):
    pass


class ProviderSettingError(ValueError):
    def __init__(self, field: str):
        super().__init__(SETTING_ERRORS[field])


class SettingsUpdate(BaseModel):
    opencode_key: SecretStr | None = None
    elevenlabs_key: SecretStr | None = None
    opencode_model: str | None = Field(default=None, max_length=112)
    elevenlabs_model: str | None = Field(default=None, max_length=100)
    elevenlabs_voice: str | None = Field(default=None, max_length=100)


class ProviderSettings:
    def __init__(self, settings: Settings):
        self.path = settings.data_dir / ".env"
        self._lock = threading.Lock()
        ai_log.configure(settings.logs_dir)

    def read(self) -> dict[str, str]:
        values = {key: os.environ.get(key, "") for key in KEYS}
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                key, _, value = line.strip().partition("=")
                if key in KEYS:
                    values[key] = value.strip().strip('"\'')
        return values

    def public(self) -> dict:
        values = self.read()
        return {"opencode_configured": bool(values["OPENCODE_GO_API_KEY"]),
                "elevenlabs_configured": bool(values["ELEVENLABS_API_KEY"]),
                "opencode_model": values["OPENCODE_GO_MODEL"],
                "elevenlabs_model": values["ELEVENLABS_MODEL"] or DEFAULT_ELEVEN_MODEL,
                "elevenlabs_voice": values["ELEVENLABS_VOICE"]}

    def update(self, updates: SettingsUpdate) -> dict:
        aliases = {"opencode_key": "OPENCODE_GO_API_KEY", "elevenlabs_key": "ELEVENLABS_API_KEY",
                   "opencode_model": "OPENCODE_GO_MODEL", "elevenlabs_model": "ELEVENLABS_MODEL",
                   "elevenlabs_voice": "ELEVENLABS_VOICE"}
        new = {}
        for field, env in aliases.items():
            value = getattr(updates, field)
            if value is None:
                continue
            if isinstance(value, SecretStr):
                value = value.get_secret_value().strip()
                if value and not re.fullmatch(r"[A-Za-z0-9_.-]{1,512}", value):
                    raise ProviderSettingError(field)
            else:
                value = value.strip()
                if field == "opencode_model" and value.startswith("opencode-go/"):
                    value = value.removeprefix("opencode-go/")
                    if not value:
                        raise ProviderSettingError(field)
                if value and not MODEL_ID.fullmatch(value):
                    raise ProviderSettingError(field)
            new[env] = value

        with self._lock:
            if not new:
                return self.public()
            old_lines = self.path.read_text(encoding="utf-8").splitlines() if self.path.is_file() else []
            lines = [line for line in old_lines if line.strip().partition("=")[0] not in new]
            lines.extend(f'{key}="{value}"' for key, value in new.items())
            fd, filename = tempfile.mkstemp(dir=self.path.parent, prefix=".env.")
            temporary = Path(filename)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    file.write("\n".join(lines) + "\n")
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
            return self.public()

    def options(self, provider: str, kind: str) -> list[dict]:
        config = self.read()
        if provider == "opencode" and kind == "models":
            key = config["OPENCODE_GO_API_KEY"]
            if not key:
                raise ProviderError("Save an OpenCode Go API key first.")
            response = _json("OpenCode Go", f"{GO}/v1/models", {"Authorization": f"Bearer {key}"})
            options = [{"id": row["id"], "name": row.get("name") or row["id"]} for row in response.get("data", [])
                       if row.get("id") and row.get("type", "chat") == "chat"]
        elif provider == "elevenlabs":
            key = config["ELEVENLABS_API_KEY"]
            if not key:
                raise ProviderError("Save an ElevenLabs API key first.")
            if kind == "models":
                response = _json("ElevenLabs", f"{ELEVEN}/v1/models", {"xi-api-key": key})
                options = [{"id": row["model_id"], "name": row.get("name") or row["model_id"]} for row in response
                           if row.get("model_id") and row.get("can_do_text_to_speech")]
            else:
                options = _voices(key)
        else:
            raise ProviderError("This provider has no speaker list.")
        return sorted(options, key=lambda option: option["name"].casefold())

    def narration_voice(self) -> dict:
        values = self.read()
        return {"provider": "elevenlabs", "voice_id": values["ELEVENLABS_VOICE"],
                "model_id": values["ELEVENLABS_MODEL"] or DEFAULT_ELEVEN_MODEL, "rate_pct": 0}

    def check_go_access(self) -> None:
        key = self.read()["OPENCODE_GO_API_KEY"]
        if not key:
            raise ProviderError("Save an OpenCode Go API key first.")
        response = _json("OpenCode Go", f"{GO}/v1/usage", {"Authorization": f"Bearer {key}"})
        if not isinstance(response, dict) or not isinstance(response.get("usage"), dict):
            raise ProviderError("OpenCode Go did not return subscription usage information.")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _error_body(error: HTTPError) -> bytes:
    with error:
        try:
            return error.read(16384)
        except OSError:
            return b""


def _http_error(provider: str, url: str, error: HTTPError, raw: bytes | None = None) -> str:
    status = error.code
    if raw is None:
        raw = _error_body(error)
    try:
        body = json.loads(raw)
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    detail = body.get("detail")
    if provider == "ElevenLabs" and isinstance(detail, dict):
        code = detail.get("status") or detail.get("code")
        if code == "missing_permissions":
            if url.endswith("/v1/models"):
                return "This ElevenLabs key needs Models → Read to load voice models. Edit the key in ElevenLabs and try again."
            if "/v2/voices?" in url:
                return "This ElevenLabs key needs Voices → Read to load speakers. Edit the key in ElevenLabs and try again."
            if "/v1/text-to-speech/" in url:
                return "This ElevenLabs key needs Text to Speech access to generate voiceover. Edit the key in ElevenLabs and try again."
        if "paid_plan_required" in (detail.get("code"), detail.get("status")):
            return ("This speaker is from the ElevenLabs Voice Library, and free plans can’t use library voices "
                    "through the API (your credits are fine). Choose one of ElevenLabs’ default speakers in AI "
                    "settings, or upgrade the ElevenLabs plan.")
        if code in ("invalid_api_key", "missing_api_key"):
            return "ElevenLabs could not authenticate the saved key. Copy the full API key from ElevenLabs and save it again."
        if code == "quota_exceeded" or status == 402:
            return "ElevenLabs reported insufficient credits for this request. Check the key’s credit limit and workspace balance."
        if code == "voice_not_found":
            return "ElevenLabs could not find this speaker. Choose a voice available to the key’s workspace."

    if provider == "OpenCode Go":
        info = body.get("error")
        if isinstance(info, dict):
            reason = info.get("message")
            if isinstance(reason, str) and "subscription required" in reason.lower():
                return "OpenCode Go requires an active Go subscription for this key. Use a key covered by your Go workspace."
            if info.get("type") == "EntitlementError":
                return "OpenCode Go does not cover this request for the saved key. Check the workspace’s Go subscription and model access."
        if status == 403 and isinstance(detail, str) and "blocked" in detail.lower():
            return "The network blocked the OpenCode Go request (HTTP 403). Try again from a connection that can reach OpenCode."
        if status == 403 and url.endswith("/v1/models"):
            return "OpenCode Go denied model listing. If this is a restricted key, enable Models → Read in OpenCode Console."

    if status in {401, 403}:
        return f"{provider} denied this request (HTTP {status}). Check the saved key and its access settings."
    if status == 429:
        return f"{provider} reached a rate or usage limit."
    return f"{provider} returned HTTP {status}. Check the selected model or voice and try again."


def _json(provider: str, url: str, headers: dict, payload: dict | None = None):
    all_headers = {"Accept": "application/json", "Content-Type": "application/json",
                   "User-Agent": f"ShortsStudio/{__version__}", **headers}
    request = Request(url, data=json.dumps(payload).encode() if payload is not None else None, headers=all_headers)
    # Every OpenCode Go call is written to data/logs/opencode-api.jsonl (keys masked; see ai_log.py).
    logged = provider == "OpenCode Go"
    entry: dict = {}
    secrets: list[str] = []
    if logged:
        safe_headers, secrets = ai_log.headers(all_headers)
        entry = {"id": ai_log.new_call_id(), "provider": provider, "method": request.get_method(), "url": url,
                 "request": {"headers": safe_headers, "body": payload}}
    started = time.monotonic()

    def finish(**result) -> None:
        if logged:
            ai_log.write({**entry, "duration_ms": round((time.monotonic() - started) * 1000), **result}, secrets)

    try:
        with build_opener(_NoRedirect).open(request, timeout=90) as response:
            status = response.status
            raw = response.read(12 * 1024 * 1024 + 1)
        if len(raw) > 12 * 1024 * 1024:
            finish(status=status, response={"body": f"<{len(raw)} bytes, too large>"},
                   error="response too large")
            raise ProviderError(f"{provider} returned a response that was too large.")
        finish(status=status, response={"body": ai_log.body(raw)})
        return json.loads(raw)
    except HTTPError as error:
        raw = _error_body(error)
        message = _http_error(provider, url, error, raw)
        finish(status=error.code, response={"body": ai_log.body(raw)}, error=message)
        raise ProviderError(message) from None
    except ProviderError:
        raise
    except (OSError, URLError, ValueError) as error:
        finish(status=None, response=None, error=f"{type(error).__name__}: {error}")
        raise ProviderError(f"Couldn’t read a response from {provider}. Try again.") from None


def _voices(key: str) -> list[dict]:
    options, page_token = [], None
    while True:
        query = {"page_size": 100}
        if page_token:
            query["next_page_token"] = page_token
        response = _json("ElevenLabs", f"{ELEVEN}/v2/voices?{urlencode(query)}", {"xi-api-key": key})
        options.extend({"id": row["voice_id"], "name": row.get("name") or row["voice_id"], "library": _is_library(row)}
                       for row in response.get("voices", []) if row.get("voice_id"))
        next_page = response.get("next_page_token")
        if not response.get("has_more") or not next_page or next_page == page_token:
            break
        page_token = next_page
    # Free plans can't use Voice Library speakers through the API (ElevenLabs answers 402 paid_plan_required), so say so
    # in the list instead of letting the generate step fail. If the plan can't be read, nothing is marked.
    try:
        free = _json("ElevenLabs", f"{ELEVEN}/v1/user/subscription", {"xi-api-key": key}).get("tier") == "free"
    except ProviderError:
        free = False
    for option in options:
        if option.pop("library") and free:
            option["name"] += " (needs a paid ElevenLabs plan)"
    return options


def _is_library(row: dict) -> bool:
    """A speaker added from the ElevenLabs Voice Library (not a default, cloned or designed voice)."""
    sharing = row.get("sharing") or {}
    return row.get("category") in ("professional", "famous") or sharing.get("status") == "copied"


def go_chat(config: dict, instructions: str, content: str | list[dict], session: str) -> str:
    response = _json("OpenCode Go", f"{GO}/openai/v1/chat/completions", {
        "Authorization": f"Bearer {config['OPENCODE_GO_API_KEY']}", "x-opencode-session": "ses_" + session[4:],
    }, {"model": config["OPENCODE_GO_MODEL"], "max_completion_tokens": 4000, "messages": [
        {"role": "system", "content": instructions}, {"role": "user", "content": content},
    ]})
    try:
        text = response["choices"][0]["message"]["content"].strip()
    except (IndexError, KeyError, TypeError, AttributeError):
        text = ""
    return text


# Shared by every AI writing task, so all of them aim at the same thing: a Short people keep watching.
SHORTS_STYLE = (
    "You write voiceover for YouTube Shorts. Your goal is a Short that stops the scroll and keeps people watching "
    "to the end. Open with a hook in the first one or two seconds: tell the viewer what to watch for, ask a question "
    "they want answered, or tease the reaction or payoff (for example \"Watch what happens when…\" or \"Wait for his "
    "reaction…\"). Talk to the viewer directly, in natural, conversational spoken English, with energy. Build "
    "curiosity and hold back the payoff until it's earned. You decide the length and wording that will work best; "
    "short punchy lines usually beat long ones. Stay truthful: tease, but never promise something the video doesn't "
    "show and never invent facts."
)


def script(config: dict, topic: str, country: str, session: str) -> str:
    market = {"CA": "Canada", "US": "the United States", "BOTH": "Canada and the United States"}[country]
    text = go_chat(config, f"{SHORTS_STYLE}\n\nWrite the full voiceover script for a Short about the topic below, "
                   f"for viewers in {market}. Put each spoken line on its own line; each line becomes one scene. "
                   "Use as many lines as the idea needs, usually 4 to 8, for a Short of roughly 20 to 45 seconds. "
                   "Return only the words to speak, without headings, numbering, Markdown or stage directions.",
                   topic, session)
    if not text or len(text) > 20000:
        raise ProviderError("OpenCode Go did not return a usable script. Try again with a different topic or model.")
    return text


def go_image_format(config: dict) -> str:
    catalog = _json("OpenCode Go", f"{GO}/v1/models", {"Authorization": f"Bearer {config['OPENCODE_GO_API_KEY']}"})
    saved = next((row for row in catalog.get("data", []) if row.get("id") == config["OPENCODE_GO_MODEL"]), {})
    inputs = (saved.get("modalities") or {}).get("input") or []
    if "image/jpeg" in inputs or "image" in inputs:
        return "image/jpeg"
    if "image/png" in inputs:
        return "image/png"
    raise ProviderError("Choose an OpenCode Go model with image input in AI settings to analyze video frames.")


def _words(alignment: dict | None) -> list[Word]:
    if not alignment:
        return []
    characters = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])
    if not len(characters) == len(starts) == len(ends) or any(len(char) != 1 for char in characters):
        return []
    return [Word(match[0], starts[match.start()], ends[match.end() - 1])
            for match in re.finditer(r"\S+", "".join(characters))]


def speech(config: dict, text: str, voice: str, model: str, rate_pct: int, work: Path) -> tuple[Path, list[Word], str]:
    key = config["ELEVENLABS_API_KEY"]
    if not key:
        raise ProviderError("Save an ElevenLabs API key in AI settings before generating voiceover.")
    if not MODEL_ID.fullmatch(voice) or not MODEL_ID.fullmatch(model):
        raise ProviderError("Choose an ElevenLabs speaker and voice model in AI settings.")
    payload: dict = {"text": text, "model_id": model}
    if rate_pct:
        payload["voice_settings"] = {"speed": 1 + rate_pct / 100}
    response = _json("ElevenLabs", f"{ELEVEN}/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128",
                     {"xi-api-key": key}, payload)
    try:
        audio = base64.b64decode(response["audio_base64"], validate=True)
        words = _words(response.get("alignment") or response.get("normalized_alignment"))
        if not audio:
            raise ValueError("Empty audio")
    except (KeyError, TypeError, ValueError):
        raise ProviderError("ElevenLabs returned unusable voice audio.") from None
    path = work / "elevenlabs.mp3"
    path.write_bytes(audio)
    return path, words, voice
